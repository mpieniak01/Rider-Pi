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
