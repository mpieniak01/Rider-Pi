"""Capture budgets across HTTP phases; isolated fixtures never actuate Pi."""

import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from navigation_runner_fixtures import isolated as isolated
from test_navigation_transport import request

from apps.compute import navigation as runner_module
from apps.compute.navigation_transport import NavigationHTTPTransport


def test_drive_http_wait_subtracts_the_age_of_its_capture(isolated):
    runner = runner_module.NavigationRunner(clock=lambda: 10.0)
    calls = []

    class Transport:
        def open(self, req, *, timeout):
            calls.append(timeout)
            return io.BytesIO(json.dumps({"source": {}}).encode())

    runner.decision_transport = Transport()
    runner._request({"age_ms": 210.0, "deadline_ms": 300}, b"fixture", "image/jpeg")
    assert calls == [pytest.approx(0.09)]


def test_failed_http_does_not_reuse_previous_success_timing(isolated):
    now = [10.0]

    def fail(*_):
        now[0] += 0.13
        raise TimeoutError("fixture timeout")

    runner = runner_module.NavigationRunner(clock=lambda: now[0], request=fail)
    runner.motion_started = True
    runner.request_roundtrip_ms = 83.09
    runner.response_age_ms = 164.09
    with pytest.raises(TimeoutError):
        runner._request_decision(
            {"run_id": runner.run_id, "frame_id": "new", "sequence": 51, "config_revision": 1},
            {"data": b"fixture", "content_type": "image/jpeg"},
            9.98,
        )
    assert runner.request_roundtrip_ms == pytest.approx(130)
    assert runner.response_age_ms == pytest.approx(150)


@pytest.mark.parametrize("phase", ["headers", "body"])
@pytest.mark.parametrize("peer", [False, True])
def test_partial_http_progress_cannot_restart_the_capture_timeout(phase, peer):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            body = json.dumps({"protocol_version": 1, "service_role": "venom", "peer_id": "a" * 32}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            seen.append(self.path)
            try:
                if phase == "headers":
                    parts = [
                        b"HTTP/1.1 200",
                        b" OK\r\n",
                        b"Content-Length: 2",
                        b"\r\n",
                        b"Content-Type: application/json\r\n\r\n",
                        b"{}",
                    ]
                else:
                    self.send_response(200)
                    self.send_header('Content-Length', '26')
                    self.end_headers()
                    parts = [b'{"state":', b'"sto', b'p",', b'"ok":', b'true', b'}']
                for part in parts:
                    self.wfile.write(part)
                    self.wfile.flush()
                    time.sleep(0.04)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    transport = NavigationHTTPTransport(
        'http://127.0.0.1:' + str(server.server_port),
        **({"transport_profile": "trusted_lan", "expected_peer_id": "a" * 32} if peer else {}),
    )
    try:
        with pytest.raises(TimeoutError):
            transport.open(request('http://127.0.0.1:' + str(server.server_port)), timeout=0.1)
        assert len(seen) == 1
        assert (transport.peer.connection if peer else transport.connection) is None
    finally:
        transport.close()
        server.shutdown()
        server.server_close()
        worker.join(1)


def test_late_journey_go_waits_in_zero_only_inside_original_feedback_window():
    from apps.compute.decision_lease import DecisionLease
    from services.navigation_config import DEFAULT

    now = [10.0]
    moves = []
    stops = []
    identity = {"version": 1, "id": "fixture-journey", "maneuver_epoch": 0}
    policy = {**DEFAULT, "mode": "drive", "verified": True, "calibration_id": "fixture", "model_sha256": "a" * 64}
    lease = DecisionLease(
        policy,
        "run",
        lambda *v: moves.append(v),
        lambda: stops.append(True),
        lambda: now[0],
        pause=lambda *_: None,
        feedback_wait=True,
        journey=identity,
    )

    def reply(sequence):
        return {
            "protocol_version": 1,
            "run_id": "run",
            "frame_id": "frame" + str(sequence),
            "sequence": sequence,
            "config_revision": policy["revision"],
            "action": "go",
            "state": "clear",
            "clear_count": 3,
            "valid_for_ms": 200,
            "model_sha256": "a" * 64,
            "journey": identity,
            "host_session": "fixture-host",
        }

    assert lease.accept(reply(1), "frame1", 1, 9.95)
    deadline = lease.feedback_deadline
    now[0] = 10.265
    assert not lease.accept(reply(2), "frame2", 2, 9.96)
    assert not lease.latched
    assert not lease.moving and lease.deadline is None
    assert lease.feedback_deadline == deadline
    assert len(moves) == 1 and not stops
    now[0] = 10.28
    assert lease.accept(reply(3), "frame3", 3, 10.26)
    assert len(moves) == 2 and not stops
    now[0] = lease.feedback_deadline + 0.001
    assert not lease.tick()
    assert lease.latched and lease.reason == "decision_timeout"


def test_expired_capture_retries_only_a_new_source_inside_existing_journey_feedback(isolated):
    from apps.compute.http_budget import CaptureBudgetExpired
    from apps.compute.journey import JourneyProgress

    now = [10.0]

    def expired(*_):
        now[0] = 10.265
        raise CaptureBudgetExpired("navigation_capture_deadline")

    runner = runner_module.NavigationRunner(clock=lambda: now[0], request=expired)
    runner.lease.journey = JourneyProgress({"version": 1, "id": "fixture-journey", "maneuver_epoch": 0}, runner.clock)
    decision = {
        "protocol_version": 1,
        "run_id": runner.run_id,
        "frame_id": "first",
        "sequence": 1,
        "config_revision": runner.policy["revision"],
        "action": "go",
        "state": "clear",
        "clear_count": 3,
        "valid_for_ms": 200,
        "model_sha256": "a" * 64,
        "journey": runner.lease.journey.context,
        "host_session": "fixture-host",
    }
    assert runner.lease.accept(decision, "first", 1, 9.95)
    feedback = runner.lease.feedback_deadline
    before = len(isolated[-1])
    now[0] = 10.07
    meta = {
        **{k: decision[k] for k in ("protocol_version", "run_id", "config_revision")},
        "frame_id": "new",
        "sequence": 2,
    }
    assert runner._request_decision(meta, {"data": b"new capture", "content_type": "image/jpeg"}, 9.96) == (False, None)
    assert runner.lease.feedback_deadline == feedback
    assert not runner.lease.latched and not runner.lease.moving
    assert len(isolated[-1]) == before
    assert runner.last_result["sequence"] == 2 and runner.last_result["action"] == "stop"
    assert runner.request_attempt["state"] == "failed"
    assert runner.request_roundtrip_ms == pytest.approx(195)
    assert runner.response_age_ms == pytest.approx(305)
    now[0] = feedback + 0.001
    assert not runner.lease.tick()
    assert runner.lease.reason == "decision_timeout"
    assert not any(x["action"] == "arm" for x in isolated[-1])


def test_inflight_timeout_diagnostics_do_not_label_last_completed_go_as_new_response(isolated):
    now = [10.0]
    seen = []

    def pending(*_):
        now[0] += 0.31
        seen.append(runner._request_diagnostics())
        raise TimeoutError("fixture timeout")

    runner = runner_module.NavigationRunner(clock=lambda: now[0], request=pending)
    runner.motion_started = True
    runner.request_roundtrip_ms = 83.09
    with pytest.raises(TimeoutError):
        runner._request_decision(
            {"run_id": runner.run_id, "sequence": 51}, {"data": b"fixture", "content_type": "image/jpeg"}, 9.92
        )
    assert seen[0]["state"] == "pending" and seen[0]["sequence"] == 51
    assert seen[0]["elapsed_ms"] == pytest.approx(310)
    assert runner.request_roundtrip_ms == pytest.approx(310)
    assert runner.request_attempt["state"] == "failed"


@pytest.fixture
def journey_lease():
    from apps.compute.decision_lease import DecisionLease
    from services.navigation_config import DEFAULT

    now, moves, stops = [10.0], [], []
    identity = {"version": 1, "id": "fixture-journey", "maneuver_epoch": 0}
    policy = {**DEFAULT, "mode": "drive", "verified": True, "calibration_id": "fixture", "model_sha256": "a" * 64}
    lease = DecisionLease(
        policy,
        "run",
        lambda *v: moves.append(v),
        lambda: stops.append(True),
        lambda: now[0],
        pause=lambda *_: None,
        feedback_wait=True,
        journey=identity,
    )

    def reply(sequence, **updates):
        return {
            "protocol_version": 1,
            "run_id": "run",
            "frame_id": "frame" + str(sequence),
            "sequence": sequence,
            "config_revision": policy["revision"],
            "action": "go",
            "state": "clear",
            "clear_count": 3,
            "valid_for_ms": 200,
            "model_sha256": "a" * 64,
            "journey": identity,
            "host_session": "fixture-host",
            **updates,
        }

    assert lease.accept(reply(1), "frame1", 1, 9.95)
    return now, moves, stops, lease, reply


@pytest.mark.parametrize(
    "updates,reason",
    [
        ({"run_id": "retired-run"}, "decision_invalid_or_expired"),
        ({"host_session": "other-host"}, "navigation_journey_identity_mismatch"),
        ({"model_sha256": "b" * 64}, "decision_invalid_or_expired"),
        ({"config_revision": -1}, "decision_invalid_or_expired"),
        ({"action": "stop", "state": "obstacle"}, "decision_invalid_or_expired"),
    ],
)
def test_late_capture_does_not_forgive_changed_identity_or_obstacle(journey_lease, updates, reason):
    now, moves, stops, lease, reply = journey_lease
    now[0] = 10.265
    assert not lease.accept(reply(2, **updates), "frame2", 2, 9.96)
    assert lease.latched and lease.reason == reason
    assert len(moves) == 1 and stops


@pytest.mark.parametrize("reason", ["operator_stop", "navigation_authority_lost", "decision_timeout"])
def test_gap_never_revives_a_retired_journey(journey_lease, reason):
    now, moves, stops, lease, reply = journey_lease
    lease.halt(reason)
    now[0] = 10.265
    assert not lease.await_fresh_capture()
    assert not lease.accept(reply(2), "frame2", 2, 10.26)
    assert lease.latched and lease.reason == reason and len(moves) == 1


def test_expired_feedback_cannot_be_extended_by_a_capture_gap(journey_lease):
    now, moves, stops, lease, reply = journey_lease
    now[0] = lease.feedback_deadline + 0.001
    assert not lease.await_fresh_capture()
    assert not lease.accept(reply(2), "frame2", 2, now[0] - 0.01)
    assert lease.reason == "decision_timeout" and lease.latched
    assert len(moves) == 1 and stops


def test_capture_preparation_that_exhausts_budget_cannot_send_a_post(isolated, monkeypatch):
    now, calls = [10.0], []
    runner = runner_module.NavigationRunner(clock=lambda: now[0])

    def slow_json(value):
        now[0] += 0.10
        return "{}"

    class Transport:
        def open(self, *_args, **_kwargs):
            calls.append(True)
            raise AssertionError("expired capture sent")

    runner.decision_transport = Transport()
    monkeypatch.setattr(runner_module.json, "dumps", slow_json)
    from apps.compute.http_budget import CaptureBudgetExpired

    with pytest.raises(CaptureBudgetExpired):
        runner._request({"age_ms": 250.0, "deadline_ms": 300}, b"fixture", "image/jpeg")
    assert not calls


def test_recorded_trial_replay_keeps_healthy_feedback_and_expires_real_missing_response(journey_lease):
    from pathlib import Path

    now, moves, stops, lease, reply = journey_lease
    recording = json.loads((Path(__file__).parent / "fixtures/navigation/production_20261023_timing.json").read_text())
    rows = recording["rows"]
    origin = rows[0]["sampled"] - (300 - rows[0]["feedback"]) / 1000
    for row in rows[:-1]:
        now[0] = 10 + row["sampled"] - origin - (300 - row["feedback"]) / 1000
        lease.accept(
            reply(row["sequence"], valid_for_ms=row["valid"]),
            "frame" + str(row["sequence"]),
            row["sequence"],
            now[0] - row["response_age"] / 1000,
        )
        assert not lease.latched
    # The terminal row retained sequence50's83ms RTT. There was no response51.
    assert rows[-1]["sequence"] == rows[-2]["sequence"]
    assert rows[-1]["rtt"] == rows[-2]["rtt"]
    now[0] = 10 + rows[-1]["sampled"] - origin
    assert not lease.tick()
    assert lease.reason == "decision_timeout" and stops


@pytest.mark.parametrize(
    "code,retry",
    [
        ("vision_frame_expired", True),
        ("stream_frame_unavailable", True),
        ("stream_epoch_changed", False),
        ("model_selection_conflict", False),
    ],
)
def test_capture_gap_retries_expiry_but_not_identity_errors(isolated, code, retry):
    import urllib.error

    from apps.compute.journey import JourneyProgress

    runner = runner_module.NavigationRunner(clock=lambda: 10.265)
    runner.lease.journey = JourneyProgress(
        {"version": 1, "id": "fixture-journey", "maneuver_epoch": 0},
        runner.clock,
    )
    runner.lease.deadline, runner.lease.feedback_deadline = 10.2, 10.3
    error = urllib.error.HTTPError(
        "http://fixture/decision",
        409,
        "fixture",
        {},
        io.BytesIO(json.dumps({"detail": {"code": code}}).encode()),
    )
    before = len(isolated[-1])
    assert runner._retry_capture_budget(error, {"run_id": runner.run_id}) is retry
    assert runner.lease.feedback_deadline == 10.3
    assert len(isolated[-1]) == before


def test_capture_gap_rechecks_manual_authority_before_retry(isolated):
    from apps.compute.http_budget import CaptureBudgetExpired
    from apps.compute.journey import JourneyProgress

    runner = runner_module.NavigationRunner(clock=lambda: 10.265)
    runner.lease.journey = JourneyProgress(
        {"version": 1, "id": "fixture-journey", "maneuver_epoch": 0},
        runner.clock,
    )
    runner.lease.deadline, runner.lease.feedback_deadline = 10.2, 10.3
    isolated[2]["owner"] = "manual"
    with pytest.raises(runner_module.ComputeError, match="navigation_authority_lost"):
        runner._retry_capture_budget(CaptureBudgetExpired(), {"run_id": runner.run_id})
    assert not any(x.get("vx") for x in isolated[-1])
