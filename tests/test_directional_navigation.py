"""No hardware: validate turn admission and regressions on the real Pi lease."""

from copy import deepcopy

import pytest

from apps.compute.decision_lease import DecisionLease
from services.navigation_config import DEFAULT, validate


def setup():
    config = deepcopy(DEFAULT)
    config.update(mode="drive", verified=True, calibration_id="accepted", model_sha256="a" * 64)
    config["perception"]["engine"] = "depth_plane"
    config["avoidance"].update(enabled=True, sweep_verified=True)
    calls = []
    now = [0.0]
    lease = DecisionLease(
        config,
        "run",
        lambda *x: calls.append(("go", *x)),
        lambda: calls.append(("stop",)),
        lambda: now[0],
        pause=lambda x: calls.append(("zero", x)),
        turn=lambda *x: calls.append(("turn", *x)),
    )
    return config, lease, now, calls


def reply(seq, **changes):
    return {
        "protocol_version": 2,
        "run_id": "run",
        "frame_id": "f" + str(seq),
        "sequence": seq,
        "config_revision": 0,
        "action": "turn_left",
        "state": "obstacle",
        "model_sha256": "a" * 64,
        "valid_for_ms": 150,
        "maneuver_clear_count": 3,
        "farther_outlier_pixels": 0,
        "sectors": {"left": {"state": "clear", "coverage_complete": True}},
        **changes,
    }


def test_turn_needs_actual_zero_cycle_and_keeps_deadline():
    _, lease, _, calls = setup()
    assert not lease.accept(reply(1, **{"action": "stop"}), "f1", 1, 0)
    assert calls[-1][0] == "zero"
    assert lease.accept(reply(2), "f2", 2, 0)
    assert calls[-1] == ("turn", "left", 0.1)
    assert lease.deadline == 0.15


def test_turn_without_stop_is_rejected():
    _, lease, _, calls = setup()
    assert not lease.accept(reply(1), "f1", 1, 0)
    assert lease.latched
    assert not any(c[0] == "turn" for c in calls)


@pytest.mark.parametrize("field,value", [("sweep_verified", False), ("max_turn_pulses", 0)])
def test_unaccepted_or_exhausted_turn_does_not_move(field, value):
    config, lease, _, calls = setup()
    config["avoidance"][field] = value
    lease.config = config
    lease.accept(reply(1, **{"action": "stop"}), "f1", 1, 0)
    assert not lease.accept(reply(2), "f2", 2, 0)
    assert not any(c[0] == "turn" for c in calls)


def test_configuration_rejects_unaccepted_driving_and_excessive_turn():
    config, _, _, _ = setup()
    assert validate(config) == config
    config["avoidance"]["turn_speed"] = 0.11
    with pytest.raises(ValueError, match="avoidance_invalid"):
        validate(config)
    config["avoidance"]["turn_speed"] = 0.05
    config["avoidance"]["sweep_verified"] = False
    with pytest.raises(ValueError, match="avoidance_not_accepted"):
        validate(config)


@pytest.mark.parametrize("sectors", [None, [], "clear", {"left": []}, {"right": {}}])
def test_malformed_or_missing_sector_never_reaches_motor(sectors):
    _, lease, _, calls = setup()
    lease.accept(reply(1, action="stop"), "f1", 1, 0)
    assert not lease.accept(reply(2, sectors=sectors), "f2", 2, 0)
    assert lease.reason == "avoidance_invalid_sector"
    assert not any(c[0] == "turn" for c in calls)


def test_protocol_v1_cannot_issue_turn_and_old_policy_still_drives():
    config, lease, _, calls = setup()
    config["avoidance"]["enabled"] = False
    assert not lease.accept(reply(1, protocol_version=1), "f1", 1, 0)
    assert lease.reason == "decision_invalid_action"
    assert not any(c[0] == "turn" for c in calls)


def test_wrong_run_old_frame_and_expired_permit_never_turn():
    for changes in ({"run_id": "other"}, {"sequence": 1}, {"valid_for_ms": 0}):
        _, lease, _, calls = setup()
        lease.accept(reply(1, action="stop"), "f1", 1, 0)
        assert not lease.accept(reply(2, **changes), "f2", 2, 0)
        assert not any(c[0] == "turn" for c in calls)


def test_pulse_and_total_turn_budget_enforced_by_pi():
    _, lease, now, calls = setup()
    for index in range(3):
        seq = index * 2 + 1
        lease.accept(reply(seq, action="stop"), "f" + str(seq), seq, now[0])
        assert lease.accept(reply(seq + 1), "f" + str(seq + 1), seq + 1, now[0])
        now[0] += 0.1
    lease.accept(reply(7, action="stop"), "f7", 7, now[0])
    assert not lease.accept(reply(8), "f8", 8, now[0])
    assert len([c for c in calls if c[0] == "turn"]) == 3
    assert all(c[2] <= 0.15 for c in calls if c[0] == "turn")
