"""No hardware: validate turn admission and regressions on the real Pi lease."""

from copy import deepcopy

import pytest

from apps.compute.decision_lease import DecisionLease
from services.navigation_config import DEFAULT, validate


def setup():
    config = deepcopy(DEFAULT)
    config.update(mode="drive", verified=True, calibration_id="accepted", model_sha256="a" * 64)
    config["perception"]["engine"] = "depth_plane"
    config["avoidance"].update(enabled=True, sweep_verified=True, protocol_version=2)
    config["avoidance"]["geometry"]["mode"] = "image"
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


@pytest.mark.parametrize("side", ["left", "right"])
def test_v3_curve_needs_no_prior_stop_but_requires_clear_path(side):
    config, lease, _, calls = setup()
    config["avoidance"]["protocol_version"] = 3
    lease.config = config
    lease.steer = lambda *x: calls.append(("steer", *x))
    row = reply(
        1,
        protocol_version=3,
        action="steer_" + side,
        sectors={side: {"state": "clear", "coverage_complete": True}},
        paths={
            side: {"state": "clear", "coverage_complete": True},
            "guard": {"state": "clear", "coverage_complete": True},
        },
    )
    assert lease.accept(row, "f1", 1, 0)
    assert calls[-1] == ("steer", side, 0.1)


@pytest.mark.parametrize("bad", [None, [], {}, {"right": {"state": "clear", "coverage_complete": True}}])
def test_v3_rejects_missing_or_forged_path_evidence(bad):
    config, lease, _, calls = setup()
    config["avoidance"]["protocol_version"] = 3
    lease.config = config
    lease.steer = lambda *x: calls.append(("steer", *x))
    assert not lease.accept(reply(1, protocol_version=3, action="steer_left", paths=bad), "f1", 1, 0)
    assert not any(row[0] == "steer" for row in calls)
    assert lease.reason == "avoidance_path_not_clear"


def test_v3_terminal_no_progress_cannot_resume_on_later_go():
    config, lease, _, calls = setup()
    config["avoidance"]["protocol_version"] = 3
    lease.config = config
    assert not lease.accept(
        reply(1, protocol_version=3, action="stop", terminal_stop=True, motion_reason="avoidance_no_progress"),
        "f1",
        1,
        0,
    )
    assert lease.latched and lease.reason == "avoidance_no_progress"
    assert not lease.accept(reply(2, protocol_version=3, action="go", state="clear", clear_count=3), "f2", 2, 0)
    assert not any(row[0] in {"go", "turn"} for row in calls)


def test_saved_legacy_avoidance_does_not_silently_become_a_curve(monkeypatch, tmp_path):
    import json

    from services import navigation_config

    config, _, _, _ = setup()
    config["avoidance"].pop("protocol_version")
    file = tmp_path / "navigation.json"
    file.write_text(json.dumps(config))
    monkeypatch.setenv("RIDER_NAVIGATION_CONFIG", str(file))
    loaded = navigation_config.snapshot()
    assert loaded["avoidance"]["protocol_version"] == 2
    assert loaded["avoidance"]["enabled"] is True


def ground_setup():
    config, lease, now, calls = setup()
    config["avoidance"].update(
        protocol_version=3, geometry={**DEFAULT["avoidance"]["geometry"], "fx": 0.5, "fy": 0.5, "radius_ratio": 0.35}
    )
    lease.steer = lambda *x: calls.append(("steer", *x))
    return config, lease, now, calls


def ground_reply(seq, **changes):
    return reply(
        seq,
        protocol_version=3,
        action="go",
        state="clear",
        clear_count=3,
        geometry="ground_capsule",
        ground_support=0.8,
        ground_reference={"normal": [0, 0.6, 0.8], "height": 1},
        **changes,
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"geometry": "image"},
        {"ground_reference": {}},
        {"ground_support": float("nan")},
        {"ground_support": 0.2},
        {"ground_support": 2.0},
        {"ground_reference": {"normal": [0, -0.6, 0.8], "height": 1}},
        {"ground_reference": {"normal": [0, 0, 2], "height": 1}},
        {"ground_reference": {"normal": [0, True, 0], "height": 1}},
        {"ground_reference": {"normal": [0, 0.6, 0.8], "height": float("inf")}},
    ],
)
def test_ground_evidence_invalid_never_reaches_motor(patch):
    _, lease, _, calls = ground_setup()
    row = ground_reply(1)
    row.update(patch)
    assert not lease.accept(row, "f1", 1, 0)
    assert lease.reason == "navigation_ground_evidence_invalid"
    assert calls == [("stop",)]


def test_ground_valid_go_uses_same_small_pulse_and_expired_go_cannot_resume():
    _, lease, now, calls = ground_setup()
    assert lease.accept(ground_reply(1), "f1", 1, 0)
    assert calls == [("go", 0.1, 0.15)]
    now[0] = 0.3
    assert not lease.tick()
    assert not lease.accept(ground_reply(2), "f2", 2, 0.3)


def test_ground_steer_validates_projection_without_new_arm_or_larger_pulse():
    _, lease, _, calls = ground_setup()
    row = ground_reply(1)
    row.update(
        action="steer_left",
        state="obstacle",
        paths={
            "left": {"state": "clear", "coverage_complete": True},
            "guard": {"state": "clear", "coverage_complete": True},
        },
    )
    assert lease.accept(row, "f1", 1, 0)
    assert calls == [("steer", "left", 0.1)]


def test_ground_go_cannot_claim_calibration_missing_in_device_policy():
    config, lease, _, calls = ground_setup()
    config["avoidance"]["geometry"]["fx"] = None
    assert not lease.accept(ground_reply(1), "f1", 1, 0)
    assert calls == [("stop",)]
    with pytest.raises(ValueError, match="navigation_geometry_calibration_required"):
        validate(config)


@pytest.mark.parametrize(
    "key,value",
    [
        ("fx", False),
        ("fy", float("nan")),
        ("radius_ratio", 0),
        ("lookahead_ratio", 9),
        ("max_heading_deg", 71),
        ("cx", 1.1),
    ],
)
def test_ground_configuration_bounds(key, value):
    config, _, _, _ = ground_setup()
    config["avoidance"]["geometry"][key] = value
    with pytest.raises(ValueError, match="navigation_geometry_invalid"):
        validate(config)


def test_legacy_geometry_migration_is_explicit_and_does_not_mutate_defaults(monkeypatch, tmp_path):
    import json

    from services import navigation_config

    original = deepcopy(DEFAULT)
    config, _, _, _ = setup()
    for key in ["geometry", "max_stalled_corrections", "progress_min_delta"]:
        config["avoidance"].pop(key)
    file = tmp_path / "navigation.json"
    file.write_text(json.dumps(config))
    monkeypatch.setenv("RIDER_NAVIGATION_CONFIG", str(file))
    loaded = navigation_config.snapshot()
    assert loaded["avoidance"]["geometry"]["mode"] == "image"
    assert loaded["avoidance"]["max_stalled_corrections"] == 2
    loaded["avoidance"]["geometry"]["fx"] = 0.8
    assert DEFAULT == original


def test_first_run_has_uncalibrated_ground_option_but_avoidance_off(monkeypatch, tmp_path):
    from services import navigation_config

    monkeypatch.setenv("RIDER_NAVIGATION_CONFIG", str(tmp_path / "missing.json"))
    config = navigation_config.snapshot()
    assert config["avoidance"]["enabled"] is False
    assert config["avoidance"]["geometry"]["mode"] == "ground"
    assert config["avoidance"]["geometry"]["fx"] is None
