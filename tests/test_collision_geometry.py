"""Versioned envelope proofs are checked offline before any motion callback."""

from copy import deepcopy

import pytest

from services import navigation_config

COLLISION = {
    "version": 1,
    "far_width_ratio": 1.0,
    "left_shift": 0.30,
    "right_shift": 0.30,
    "end_fraction": 0.2,
    "reference_corridor": [0.35, 0.65, 0.65, 0.95],
}


def policy():
    value = deepcopy(navigation_config.DEFAULT)
    value["perception"]["engine"] = "depth_plane"
    value["avoidance"].update(enabled=True, sweep_verified=True)
    value["avoidance"]["geometry"].update(mode="image", collision=deepcopy(COLLISION))
    return value


def test_device_accepts_explicit_envelopes_without_starting_motion():
    config = policy()
    assert navigation_config.validate(config) == config


@pytest.mark.parametrize(
    "change",
    [
        {"version": True},
        {"version": 2},
        {"far_width_ratio": 0},
        {"right_shift": float("nan")},
        {"end_fraction": 0},
        {"reference_corridor": [0.4, 0.9, 0.6, 0.95]},
        {"unexpected": 1},
    ],
)
def test_device_rejects_unqualified_geometry(change):
    config = policy()
    config["avoidance"]["geometry"]["collision"].update(change)
    with pytest.raises(ValueError, match="collision"):
        navigation_config.validate(config)


def command(config, *, action="steer_left"):
    from services.collision_geometry import proof

    clear = {"state": "clear", "coverage_complete": True, "geometry": "image_collision_corridor", "zone_pixels": 100}
    return {
        "protocol_version": 3,
        "run_id": "offline",
        "frame_id": "f1",
        "sequence": 1,
        "config_revision": config["revision"],
        "valid_for_ms": 200,
        "model_sha256": "a" * 64,
        "action": action,
        "state": "clear" if action == "go" else "obstacle",
        "reason": "fixture",
        "clear_count": 3,
        "maneuver_clear_count": 3,
        "farther_outlier_pixels": 0,
        "geometry": "image_collision_corridor",
        "collision_geometry": proof(config),
        "sectors": {"left": {"state": "obstacle"}, "right": {"state": "obstacle"}},
        "paths": {key: dict(clear) for key in ("left", "right", "center", "guard")},
    }


def drive_policy():
    config = policy()
    config.update(mode="drive", verified=True, calibration_id="offline", model_sha256="a" * 64)
    return config


def lease(config, outputs):
    from apps.compute.decision_lease import DecisionLease

    return DecisionLease(
        config,
        "offline",
        lambda *args: outputs.append(("go", *args)),
        lambda: outputs.append(("halt",)),
        steer=lambda *args: outputs.append(("steer", *args)),
        pause=lambda *args: outputs.append(("zero", *args)),
        clock=lambda: 0.0,
    )


def test_device_uses_maneuver_proof_instead_of_unrelated_side_rectangles():
    config, outputs = drive_policy(), []
    permit = lease(config, outputs)
    assert permit.accept(command(config), "f1", 1, 0.0)
    assert outputs == [("steer", "left", 0.1)]


@pytest.mark.parametrize("action", ["go", "steer_left"])
@pytest.mark.parametrize(
    "fault",
    ["missing", "hash", "boolean_version", "coverage", "guard", "type", "pixels", "expired", "revision", "side"],
)
def test_invalid_or_stale_proof_never_reaches_a_motor_callback(action, fault):
    config, outputs = drive_policy(), []
    decision = command(config, action=action)
    if fault == "missing":
        decision.pop("collision_geometry")
    elif fault == "hash":
        decision["collision_geometry"]["sha256"] = "0" * 64
    elif fault == "boolean_version":
        decision["collision_geometry"]["version"] = True
    elif fault == "coverage":
        decision["paths"]["center"]["coverage_complete"] = False
    elif fault == "guard":
        decision["paths"]["guard"]["state"] = "obstacle"
    elif fault == "type":
        decision["geometry"] = "image"
    elif fault == "pixels":
        decision["paths"]["guard"]["zone_pixels"] = True
    elif fault == "expired":
        decision["valid_for_ms"] = 0
    elif fault == "revision":
        decision["config_revision"] += 1
    elif fault == "side":
        decision["paths"]["left"]["state"] = "obstacle"
        if action == "go":  # a blocked turn is irrelevant to a clear forward corridor
            assert lease(config, outputs).accept(decision, "f1", 1, 0.0)
            assert outputs[0][0] == "go"
            return
    assert not lease(config, outputs).accept(decision, "f1", 1, 0.0)
    assert outputs == [("halt",)]


@pytest.mark.parametrize("capability", [None, False, 1])
def test_old_host_cannot_negotiate_new_geometry(capability):
    from apps.compute.client import ComputeError
    from services.collision_geometry import require_host

    with pytest.raises(ComputeError, match="navigation_collision_update_required"):
        require_host({"collision_geometry_v1": capability}, 1)


def test_legacy_configuration_never_accepts_unsolicited_new_geometry():
    config, outputs = drive_policy(), []
    decision = command(config)
    config["avoidance"]["geometry"].pop("collision")
    assert not lease(config, outputs).accept(decision, "f1", 1, 0.0)
    assert outputs == [("halt",)]


def test_geometry_edit_revokes_old_approval_but_explicit_reapproval_survives(monkeypatch, tmp_path):
    saved = []
    config = drive_policy()
    monkeypatch.setenv("RIDER_NAVIGATION_CONFIG", str(tmp_path / "navigation.json"))
    monkeypatch.setattr(navigation_config, "snapshot", lambda: deepcopy(config))
    monkeypatch.setattr(navigation_config, "_require_configuration_goals_stopped", lambda *_: None)
    monkeypatch.setattr(navigation_config, "_write", lambda _path, value: saved.append(value))
    avoidance = deepcopy(config["avoidance"])
    avoidance["geometry"]["collision"]["far_width_ratio"] = 0.7
    changed = navigation_config.configure_locked(
        {
            "revision": config["revision"],
            "values": {"avoidance": avoidance, "verified": True, "calibration_id": "cannot-approve-an-unseen-edit"},
        }
    )
    assert changed["mode"] == "observe"
    assert changed["verified"] is False
    assert changed["avoidance"]["sweep_verified"] is False
    config = changed
    approved = navigation_config.configure_locked(
        {
            "revision": config["revision"],
            "values": {
                "verified": True,
                "calibration_id": "new-observed-geometry",
                "avoidance": {**deepcopy(config["avoidance"]), "sweep_verified": True},
            },
        }
    )
    assert approved["verified"] is True
    assert approved["avoidance"]["sweep_verified"] is True
    assert approved["mode"] == "observe"
    assert len(saved) == 2


def test_crop_cannot_hide_independent_floor_reference():
    config = policy()
    config["avoidance"]["geometry"]["collision"]["reference_corridor"] = [0.2, 0.5, 0.8, 0.95]
    config["perception"]["input_region"] = {"version": 1, "bounds": [0.3, 0.6, 0.7, 1.0]}
    with pytest.raises(ValueError, match="navigation_input_region_excludes_reference"):
        navigation_config.validate(config)


@pytest.mark.parametrize("avoidance", [None, [], {"geometry": None}])
def test_malformed_geometry_is_a_configuration_error_without_persistence(monkeypatch, tmp_path, avoidance):
    config = drive_policy()
    monkeypatch.setenv("RIDER_NAVIGATION_CONFIG", str(tmp_path / "navigation.json"))
    monkeypatch.setattr(navigation_config, "snapshot", lambda: deepcopy(config))
    monkeypatch.setattr(navigation_config, "_require_configuration_goals_stopped", lambda *_: None)
    with pytest.raises(ValueError, match="navigation_avoidance_invalid"):
        navigation_config.configure_locked({"revision": config["revision"], "values": {"avoidance": avoidance}})
    assert not (tmp_path / "navigation.json").exists()


def test_pi_status_records_submitted_command_without_claiming_motion(monkeypatch, tmp_path):
    import json

    from navigation_runner_fixtures import isolated as _fixture  # fixture body is inert

    from apps.compute import navigation

    # Reuse the established fixture without invoking a runner or camera loop.
    setup = _fixture.__wrapped__(monkeypatch, tmp_path)
    runner = navigation.NavigationRunner(clock=lambda: 0.0)
    monkeypatch.setattr(runner, "_authority", lambda: True)
    runner.last_result = {"frame_id": "observed-frame"}
    runner.drive(0.1, 0.1, yaw=-0.2)
    runner._write_status(runner.last_result)
    command = json.loads((tmp_path / "status.json").read_text())["motion_submission"]
    assert command["frame_id"] == "observed-frame"
    assert (command["vx"], command["yaw"], command["duration_ms"]) == (0.1, -0.2, 100)
    assert command["status"] == "accepted"
    assert "observed_motion" not in command
    assert setup[-1][-1]["yaw"] == -0.2
