"""Recovery of the recorded first-capture timeout; no hardware or network."""

import io
import json
import urllib.error

import pytest
from navigation_runner_fixtures import isolated as isolated

from apps.compute.http_budget import CaptureBudgetExpired
from apps.compute.navigation import NavigationRunner


def prepare(isolated, now, journey):
    _, _, safety, _, commands = isolated
    safety.update(
        state="ARMED",
        panel_control={"version": 1, "holder": "fixture"},
        operator_control={"version": 1, "state": "qualifying", "operation_id": "initial"},
    )
    if journey:
        safety.update(
            arming_mode="journey",
            navigation_journey_version=1,
            journey={"version": 1, "id": "fixture-journey", "active": True},
        )
    runner = NavigationRunner(clock=lambda: now[0])
    assert runner._authority()
    assert runner.operator_lifecycle.enabled
    return runner, safety, commands


def metadata(runner, sequence):
    return {
        "protocol_version": 1,
        "run_id": runner.run_id,
        "frame_id": "capture-" + str(sequence),
        "sequence": sequence,
        "config_revision": runner.policy["revision"],
        "age_ms": 153.9,
    }


def error(kind):
    if kind == "capture":
        return CaptureBudgetExpired("navigation_capture_deadline")
    status, code = (429, "vision_busy") if kind == "busy" else (409, "vision_frame_expired")
    body = io.BytesIO(json.dumps({"detail": {"code": code}}).encode())
    return urllib.error.HTTPError("http://fixture.invalid", status, "fixture", {}, body)


@pytest.mark.parametrize("journey", [False, True])
@pytest.mark.parametrize("kind", ["capture", "expired", "busy"])
def test_first_capture_can_expire_without_ending_the_original_startup(isolated, journey, kind):
    now = [10.0]
    runner, _, commands = prepare(isolated, now, journey)
    lease, deadline, epoch = runner.lease, runner.startup_deadline, runner.run_id

    def request(*_):
        now[0] = 10.302
        raise error(kind)

    runner.request = request
    now[0] = 10.1539
    assert runner._request_decision(metadata(runner, 1), {"data": b"fixture", "content_type": "image/jpeg"}, 10.0) == (
        False,
        None,
    )
    assert runner.policy["mode"] == "drive"
    assert runner.run_id == epoch
    assert runner.lease is lease
    assert not lease.latched
    assert runner.startup_deadline == deadline
    assert lease.deadline is None
    assert lease.feedback_deadline is None
    assert commands == []
    assert runner.last_result["action"] == "stop"
    assert runner.request_attempt["state"] == "failed"


@pytest.mark.parametrize("journey", [False, True])
def test_recovery_still_needs_three_new_frames_before_any_inert_move(isolated, journey):
    now = [10.0]
    runner, _, commands = prepare(isolated, now, journey)
    runner.operator_lifecycle.qualification.count = 2

    def expired(*_):
        now[0] = 10.302
        raise CaptureBudgetExpired("navigation_capture_deadline")

    runner.request = expired
    runner._request_decision(metadata(runner, 1), {"data": b"x", "content_type": "image/jpeg"}, 10.0)
    assert runner.operator_lifecycle.qualification.count == 0

    def reply(meta, *_):
        return {
            **{key: meta[key] for key in ("protocol_version", "run_id", "frame_id", "sequence", "config_revision")},
            "state": "clear",
            "action": "go",
            "clear_count": 900,
            "model_sha256": "a" * 64,
            "valid_for_ms": 150,
            **({"journey": runner.lease.journey.context, "host_session": "fixture"} if journey else {}),
        }

    runner.request = reply
    for sequence in range(2, 5):
        now[0] += 0.05
        runner.sequence = sequence
        meta = metadata(runner, sequence)
        received, decision = runner._request_decision(
            meta, {"data": b"new capture", "content_type": "image/jpeg"}, now[0]
        )
        assert received
        runner._apply_decision(decision, meta, now[0])
        moves = [row for row in commands if row.get("action") == "move" and row.get("vx")]
        assert len(moves) == (1 if sequence == 4 else 0)
    assert not any(row["action"] == "arm" for row in commands)


@pytest.mark.parametrize("block", ["deadline", "closed", "latched", "stale_run", "manual", "disarmed"])
def test_startup_retry_cannot_extend_time_or_restore_revoked_authority(isolated, block):
    now = [10.0]
    runner, safety, commands = prepare(isolated, now, True)
    meta = metadata(runner, 1)
    initial_deadline = runner.startup_deadline
    if block == "deadline":
        now[0] = initial_deadline + 0.001
    elif block == "closed":
        runner.closed.set()
    elif block == "latched":
        runner.lease.halt("fixture-terminal")
    elif block == "stale_run":
        meta["run_id"] = "old-epoch"
    elif block == "manual":
        safety.update(owner="manual", generation="new-manual")
    else:
        safety.update(state="DISARMED", can_move=False, owner=None)
    assert not runner._retry_capture_budget(CaptureBudgetExpired(), meta)
    assert runner.startup_deadline == initial_deadline or runner.policy["mode"] == "observe"
    assert not any(row.get("vx") or row["action"] == "arm" for row in commands)


def test_generic_network_errors_do_not_use_the_capture_startup_exception(isolated):
    now = [10.0]
    runner, _, commands = prepare(isolated, now, True)
    for failure in [TimeoutError(), ConnectionError(), error("expired")]:
        if isinstance(failure, urllib.error.HTTPError):
            failure.code = 401
        assert not runner._retry_capture_budget(failure, metadata(runner, 1))
    assert commands == []


def test_repeated_expired_captures_share_the_original_five_second_window(isolated):
    now = [10.0]
    runner, _, commands = prepare(isolated, now, True)
    deadline = runner.startup_deadline
    for sequence in range(1, 15):
        now[0] += 0.302
        assert runner._retry_capture_budget(CaptureBudgetExpired(), metadata(runner, sequence))
        assert runner.startup_deadline == deadline
        assert runner.lease.deadline is None
        assert runner.lease.feedback_deadline is None
    now[0] = deadline
    assert not runner._retry_capture_budget(CaptureBudgetExpired(), metadata(runner, 15))
    assert commands == []


def test_startup_does_not_override_an_existing_zero_permit_or_feedback_deadline(isolated):
    now = [10.0]
    runner, _, commands = prepare(isolated, now, True)
    runner.lease.deadline = 10.2
    runner.lease.feedback_deadline = 10.3
    now[0] = 10.15
    assert not runner._retry_capture_budget(CaptureBudgetExpired(), metadata(runner, 1))
    assert runner.lease.deadline == 10.2
    assert runner.lease.feedback_deadline == 10.3
    now[0] = 10.25
    assert runner._retry_capture_budget(CaptureBudgetExpired(), metadata(runner, 2))
    assert runner.lease.deadline is None
    assert runner.lease.feedback_deadline == 10.3
    assert commands == []
