import pytest

from apps.compute.decision_lease import DecisionLease
from services.navigation_config import DEFAULT, configure, snapshot, validate


def make():
    now = [0.0]
    calls = []
    config = {**DEFAULT, "mode": "drive", "verified": True, "calibration_id": "trial", "model_sha256": "a" * 64}
    lease = DecisionLease(
        config,
        "run",
        lambda speed, duration: calls.append(("go", speed, duration)),
        lambda: calls.append(("stop",)),
        lambda: now[0],
    )
    return lease, now, calls


def decision(seq=1, **kw):
    return {
        "protocol_version": 1,
        "run_id": "run",
        "frame_id": "f" + str(seq),
        "sequence": seq,
        "config_revision": 0,
        "action": "go",
        "state": "clear",
        "clear_count": 3,
        "valid_for_ms": 150,
        "model_sha256": "a" * 64,
        **kw,
    }


def test_no_feedback_stops_and_delayed_reply_cannot_resume():
    lease, now, calls = make()
    assert lease.accept(decision(), "f1", 1, 0)
    now[0] = 0.151
    assert not lease.tick()
    assert calls[-1] == ("stop",)
    assert not lease.accept(decision(2), "f2", 2, now[0])
    assert len([x for x in calls if x[0] == "go"]) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"run_id": "old"},
        {"sequence": 0},
        {"config_revision": 1},
        {"state": "unknown"},
        {"model_sha256": "b" * 64},
        {"valid_for_ms": True},
        {"action": "turn"},
        {"clear_count": 1},
    ],
)
def test_invalid_reply_never_moves(change):
    lease, _, calls = make()
    assert not lease.accept(decision(**change), "f1", 1, 0)
    assert lease.latched
    assert all(x[0] != "go" for x in calls)


def test_obstacle_latches_stop():
    lease, _, calls = make()
    assert lease.accept(decision(), "f1", 1, 0)
    assert not lease.accept(decision(2, action="stop", state="obstacle"), "f2", 2, 0)
    assert lease.latched
    assert calls[-1] == ("stop",)


def test_expired_source_and_replay():
    lease, now, _ = make()
    now[0] = 0.4
    assert not lease.accept(decision(), "f1", 1, 0)
    lease, now, _ = make()
    assert lease.accept(decision(), "f1", 1, 0)
    assert not lease.accept(decision(), "f1", 1, 0)


def test_clear_warmup_does_not_disarm():
    lease, _, calls = make()
    assert not lease.accept(decision(action="stop", clear_count=1), "f1", 1, 0)
    assert not lease.latched
    assert calls == []


def test_model_error_stops_initial_run():
    lease, _, calls = make()
    assert not lease.accept(decision(action="stop", state="unknown"), "f1", 1, 0)
    assert lease.latched


@pytest.mark.parametrize(
    "change",
    [
        {"speed": True},
        {"speed": 0.2},
        {"decision_budget_ms": 1000},
        {"corridor": [0.5, 0.5, 0.1, 0.9]},
        {"mode": "drive"},
        {"verified": "true"},
        {"model_sha256": "invalid"},
    ],
)
def test_policy_bounds(change):
    with pytest.raises(ValueError):
        validate({**DEFAULT, **change})


def test_persisted_policy_is_revisioned_and_default_observe(tmp_path, monkeypatch):
    monkeypatch.setenv("RIDER_NAVIGATION_CONFIG", str(tmp_path / "policy.json"))
    monkeypatch.setenv("FEATURE_STATE_PATH", str(tmp_path / "features.json"))
    assert snapshot()["mode"] == "observe"
    result = configure({"revision": 0, "values": {"speed": 0.12}})
    assert result["revision"] == 1
    assert snapshot() == result
    with pytest.raises(ValueError):
        configure({"revision": 0, "values": {"speed": 0.1}})


def test_bus_delay_cannot_extend_decision_duration():
    from apps.motion.actuator_contract import decision_duration

    command = {"source": "navigation", "execution_context": "panel", "decision_deadline_monotonic": 10.15}
    assert decision_duration(command, 0.15, 10.1) == pytest.approx(0.05)
    with pytest.raises(ValueError, match="expired"):
        decision_duration(command, 0.15, 10.16)
    with pytest.raises(ValueError, match="source"):
        decision_duration({**command, "source": "manual"}, 0.15, 10.1)
    assert decision_duration({}, 0.15, 10.1) == 0.15


def test_fresh_reply_after_pulse_end_keeps_the_valid_navigation_run():
    lease, now, calls = make()
    assert lease.accept(decision(valid_for_ms=200), "f1", 1, 0)
    assert calls[-1][2] == pytest.approx(0.15)
    assert lease.deadline == pytest.approx(0.2)
    now[0] = 0.16
    assert lease.tick()
    assert lease.accept(decision(2, valid_for_ms=200), "f2", 2, now[0])
    assert calls[-1][2] <= 0.15
    assert lease.deadline == pytest.approx(0.36)
    now[0] = 0.361
    assert not lease.tick()
    assert calls[-1] == ("stop",)
    assert not lease.accept(decision(3, valid_for_ms=200), "f3", 3, now[0])


def test_lease_freshness_never_extends_the_captured_frame_budget():
    lease, now, calls = make()
    now[0] = 0.24
    assert lease.accept(decision(valid_for_ms=200), "f1", 1, 0)
    assert calls[-1][2] == pytest.approx(0.06)
    assert lease.deadline == pytest.approx(0.3)
    now[0] = 0.301
    assert not lease.tick()


def test_new_policy_uses_near_zone_without_increasing_motion(tmp_path, monkeypatch):
    monkeypatch.setenv("RIDER_NAVIGATION_CONFIG", str(tmp_path / "policy.json"))
    policy = snapshot()
    assert policy["corridor"] == [0.35, 0.80, 0.65, 0.95]
    assert policy["speed"] == 0.1
    assert policy["max_motion_ms"] == 150
    assert policy["mode"] == "observe"
    assert policy["verified"] is False


def test_zone_change_invalidates_only_receipt_not_motion_limits(tmp_path, monkeypatch):
    import json

    target = tmp_path / "policy.json"
    monkeypatch.setenv("RIDER_NAVIGATION_CONFIG", str(target))
    monkeypatch.setenv("FEATURE_STATE_PATH", str(tmp_path / "features.json"))
    original = {
        **DEFAULT,
        "revision": 7,
        "mode": "drive",
        "verified": True,
        "calibration_id": "original",
        "model_sha256": "a" * 64,
        "corridor": [0.35, 0.65, 0.65, 0.95],
    }
    target.write_text(json.dumps(original))
    # Existing saved zones are not silently rewritten by a default change.
    assert snapshot() == original
    saved = configure({"revision": 7, "values": {"corridor": [0.35, 0.80, 0.65, 0.95]}})
    assert saved["revision"] == 8
    assert saved["verified"] is False
    assert saved["mode"] == "observe"
    for key in ("speed", "max_motion_ms", "decision_budget_ms"):
        assert saved[key] == original[key]


class BoundedExecutor:
    """Independent hardware deadline/pulse enforcement, not a retained speed."""

    def __init__(self, now):
        self.now = now
        self.until = 0.0
        self.commands = []
        self.revoked = False
        self.lease = None

    @property
    def speed(self):
        return self.commands[-1][0] if self.commands and self.now[0] < self.until else 0.0

    def drive(self, speed, duration):
        assert not self.revoked
        self.until = min(self.now[0] + duration, self.lease.deadline)
        self.commands.append((speed, duration, self.until))

    def stop(self):
        self.until = self.now[0]
        self.revoked = True


def feedback_loop():
    now = [0.0]
    output = BoundedExecutor(now)
    config = {**DEFAULT, "mode": "drive", "verified": True, "model_sha256": "a" * 64}
    lease = DecisionLease(
        config,
        "run",
        output.drive,
        output.stop,
        lambda: now[0],
        pause=lambda duration: output.drive(0, duration),
        feedback_wait=True,
    )
    output.lease = lease
    return lease, now, output


def test_recorded_production_go_gap_stops_motor_but_accepts_next_fresh_reply():
    import json
    from pathlib import Path

    trace = json.loads((Path(__file__).parent / "fixtures/navigation/production_1245_timing.json").read_text())
    go = [r for r in trace["rows"] if r["action"] == "go"]
    first, following = go[0], go[1]
    permit_ms = min(300 - first["response_age_ms"], first["valid_for_ms"])
    callback_ms = permit_ms - first["permit_remaining_ms"]
    admitted = first["sampled_monotonic"] - callback_ms / 1000
    gap = following["sampled_monotonic"] - admitted
    lease, now, output = feedback_loop()
    assert lease.accept(decision(4, valid_for_ms=first["valid_for_ms"]), "f4", 4, -first["response_age_ms"] / 1000)
    assert output.speed == DEFAULT["speed"]
    old_deadline = lease.deadline
    now[0] = old_deadline + 0.00001
    assert lease.tick()
    assert output.speed == 0
    assert not output.revoked
    assert lease.deadline is None
    assert not lease.moving
    assert lease.reason == "awaiting_fresh_decision"
    now[0] = gap
    assert lease.accept(
        decision(5, valid_for_ms=following["valid_for_ms"]), "f5", 5, gap - following["response_age_ms"] / 1000
    )
    assert len(output.commands) == 2
    assert not output.revoked
    assert output.speed == DEFAULT["speed"]
    assert output.commands[0][2] == old_deadline
    assert all(duration <= 0.150 for _, duration, _ in output.commands)


def test_lost_feedback_zeros_at_original_permit_and_is_terminal_at_existing_budget():
    lease, now, output = feedback_loop()
    assert lease.accept(decision(valid_for_ms=100), "f1", 1, 0)
    now[0] = 0.101
    assert output.speed == 0
    assert lease.tick()
    assert not lease.moving
    assert lease.feedback_deadline == 0.3
    now[0] = 0.3
    assert not lease.tick()
    assert output.revoked
    assert not lease.accept(decision(2), "f2", 2, now[0])
    assert len(output.commands) == 1


@pytest.mark.parametrize("change", [{"run_id": "foreign"}, {"valid_for_ms": 0}, {"frame_id": "foreign"}])
def test_bad_reply_in_zero_gap_cannot_resume(change):
    lease, now, output = feedback_loop()
    assert lease.accept(decision(valid_for_ms=50), "f1", 1, 0)
    now[0] = 0.06
    assert lease.tick()
    assert output.speed == 0
    assert not lease.accept(decision(2, **change), "f2", 2, now[0])
    assert output.revoked
    assert len(output.commands) == 1


@pytest.mark.parametrize("reason", ["operator_stop", "navigation_transport_or_input_failed"])
def test_explicit_stop_and_transport_fault_are_terminal_during_zero_wait(reason):
    lease, now, output = feedback_loop()
    assert lease.accept(decision(valid_for_ms=50), "f1", 1, 0)
    now[0] = 0.06
    lease.tick()
    lease.halt(reason)
    assert not lease.accept(decision(2), "f2", 2, now[0])
    assert output.revoked
    assert len(output.commands) == 1


def test_recorded_151611_short_go_sends_only_zero_then_accepts_a_new_fresh_frame():
    import json
    from pathlib import Path

    trace = json.loads((Path(__file__).parent / "fixtures/navigation/production_151611_timing.json").read_text())
    lease, now, output = feedback_loop()
    prior, short = trace["prior"], trace["short"]
    assert lease.accept(
        decision(prior["sequence"], valid_for_ms=prior["valid_for_ms"]),
        "f49",
        prior["sequence"],
        -prior["response_age_ms"] / 1000,
    )
    old_motion_end = output.until
    old_feedback = lease.feedback_deadline
    now[0] = short["elapsed_since_prior_accept_ms"] / 1000
    assert now[0] < old_feedback
    assert output.speed == 0
    assert not lease.accept(
        decision(short["sequence"], valid_for_ms=short["valid_for_ms"]),
        "f50",
        short["sequence"],
        now[0] - short["response_age_ms"] / 1000,
    )
    assert not lease.latched
    assert not output.revoked
    assert lease.reason == "awaiting_fresh_decision"
    assert not lease.moving
    assert output.commands[-1][0] == 0
    assert output.speed == 0
    assert output.commands[0][2] == old_motion_end
    # Replay ends at the historical failure. This next fresh frame tests recovery.
    now[0] = 0.35
    assert lease.accept(decision(51), "f51", 51, now[0] - 0.09)
    assert output.speed == DEFAULT["speed"]
    assert all(duration <= 0.15 for _, duration, _ in output.commands)


def test_short_reply_zero_window_still_expires_without_further_feedback():
    lease, now, output = feedback_loop()
    now[0] = 0.296
    assert not lease.accept(decision(), "f1", 1, 0)
    assert output.speed == 0
    assert not lease.latched
    deadline = lease.feedback_deadline
    now[0] = deadline
    assert not lease.tick()
    assert output.revoked
    assert not lease.accept(decision(2), "f2", 2, now[0])
    assert all(speed == 0 for speed, _, _ in output.commands)


@pytest.mark.parametrize("change", [{"run_id": "wrong"}, {"model_sha256": "b" * 64}, {"valid_for_ms": 0}])
def test_short_reply_does_not_bypass_identity_model_or_validity(change):
    lease, now, output = feedback_loop()
    now[0] = 0.296
    assert not lease.accept(decision(**change), "f1", 1, 0)
    assert lease.latched
    assert output.revoked
    assert output.commands == []


def test_expired_reply_is_terminal_even_with_zero_wait_support():
    lease, now, output = feedback_loop()
    now[0] = 0.301
    assert not lease.accept(decision(), "f1", 1, 0)
    assert lease.latched
    assert output.revoked
    assert output.commands == []


def test_legacy_short_permit_still_stops_terminally():
    lease, now, calls = make()
    now[0] = 0.296
    assert not lease.accept(decision(), "f1", 1, 0)
    assert lease.latched
    assert calls == [("stop",)]


def test_short_reply_cannot_recover_after_feedback_has_expired():
    lease, now, output = feedback_loop()
    assert lease.accept(decision(), "f1", 1, 0)
    now[0] = 0.301
    assert not lease.accept(decision(2), "f2", 2, now[0] - 0.296)
    assert lease.reason == "decision_timeout"
    assert output.revoked


def test_zero_submission_failure_remains_terminal():
    lease, now, output = feedback_loop()
    lease.pause = lambda _: (_ for _ in ()).throw(RuntimeError("bus unavailable"))
    now[0] = 0.296
    command = decision()
    with pytest.raises(RuntimeError, match="bus unavailable"):
        lease.accept(command, "f1", 1, 0)
    assert lease.latched
    assert output.revoked
    assert lease.reason == "motion_submission_failed"


@pytest.mark.parametrize("duration", [190, 250])
def test_extended_navigation_pulse_policy_accepts_without_changing_defaults(duration):
    from copy import deepcopy

    policy = deepcopy(DEFAULT)
    policy.update(max_motion_ms=duration)
    policy["perception"]["engine"] = "depth_plane"
    policy["avoidance"]["enabled"] = True
    assert validate(policy)["max_motion_ms"] == duration
    assert DEFAULT["max_motion_ms"] == 150
    with pytest.raises(ValueError, match="navigation_duration_invalid"):
        validate({**policy, "max_motion_ms": 251})


@pytest.mark.parametrize(
    "limit,valid_ms,age,expected", [(190, 200, 0, 0.19), (250, 200, 0, 0.2), (250, 150, 0, 0.15), (250, 200, 0.2, 0.1)]
)
def test_extended_pulse_never_exceeds_reply_or_capture_deadline(limit, valid_ms, age, expected):
    lease, now, calls = make()
    lease.config["max_motion_ms"] = limit
    now[0] = age
    assert lease.accept(decision(valid_for_ms=valid_ms), "f1", 1, 0)
    assert calls[-1][2] == pytest.approx(expected)
    now[0] = lease.deadline + 0.001
    assert not lease.tick()
    assert calls[-1] == ("stop",)
    assert not lease.accept(decision(2, valid_for_ms=valid_ms), "f2", 2, now[0])
