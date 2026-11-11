"""Pi admits the configured maneuver kind only with its own body evidence."""

from copy import deepcopy

import pytest
from test_collision_geometry import command, drive_policy, lease

from services import navigation_config


def guided(mode="rotate_then_drive"):
    config = drive_policy()
    config["avoidance"]["geometry"]["collision"]["guidance"] = {
        "version": 1,
        "motion_mode": mode,
        "center_deadband": 0.1,
        "rotation_bounds": [0.2, 0.88, 0.8, 0.95],
    }
    return config


def reply(config, action="turn_right", sequence=1):
    result = command(config, action=action)
    result.update(sequence=sequence, frame_id="f" + str(sequence))
    result["guidance"] = {
        "version": 1,
        "motion_mode": config["avoidance"]["geometry"]["collision"]["guidance"]["motion_mode"],
    }
    result["paths"]["rotation"] = deepcopy(result["paths"]["guard"])
    return result


def test_device_accepts_guidance_configuration():
    assert navigation_config.validate(guided()) == guided()


def test_rotation_needs_explicit_zero_and_independent_rotation_footprint():
    config, outputs = guided(), []
    permit = lease(config, outputs)
    permit.turn = lambda *args: outputs.append(("turn", *args))
    stop = reply(config, "stop")
    permit.accept(stop, "f1", 1, 0.0)
    assert permit.accept(reply(config, sequence=2), "f2", 2, 0.0)
    assert outputs == [("zero", 0.15), ("turn", "right", 0.1)]


@pytest.mark.parametrize(
    "fault", ["no_zero", "rotation_blocked", "rotation_missing", "rotation_unobserved", "wrong_mode", "wrong_proof"]
)
def test_invalid_rotation_never_reaches_turn_callback(fault):
    config, outputs = guided(), []
    permit = lease(config, outputs)
    permit.turn = lambda *args: outputs.append(("turn", *args))
    permit.paused_for_obstacle = fault != "no_zero"
    decision = reply(config)
    if fault == "rotation_blocked":
        decision["paths"]["rotation"]["state"] = "obstacle"
    if fault == "rotation_missing":
        decision["paths"].pop("rotation")
    if fault == "rotation_unobserved":
        decision["paths"]["rotation"]["coverage_complete"] = False
    if fault == "wrong_mode":
        decision["guidance"]["motion_mode"] = "steer"
    if fault == "wrong_proof":
        decision["collision_geometry"]["sha256"] = "0" * 64
    assert not permit.accept(decision, "f1", 1, 0.0)
    assert outputs == [("halt",)]


def test_rotate_mode_cannot_receive_curved_motion_and_legacy_v3_cannot_rotate():
    for config, action in [(guided(), "steer_left"), (drive_policy(), "turn_left")]:
        outputs = []
        decision = (
            reply(config, action)
            if "guidance" in config["avoidance"]["geometry"]["collision"]
            else command(config, action=action)
        )
        assert not lease(config, outputs).accept(decision, "f1", 1, 0.0)
        assert outputs == [("halt",)]


def test_observe_can_save_missing_rotation_calibration_but_drive_cannot():
    config = guided()
    config["avoidance"]["geometry"]["collision"]["guidance"]["rotation_bounds"] = None
    with pytest.raises(ValueError, match="rotation"):
        navigation_config.validate(config)
    config.update(mode="observe", verified=False)
    assert navigation_config.validate(config) == config


def test_after_rotation_pre_correction_capture_cannot_command_forward():
    config, outputs = guided(), []
    permit = lease(config, outputs)
    permit.turn = lambda *args: outputs.append(("turn", *args))
    permit.paused_for_obstacle = True
    assert permit.accept(reply(config), "f1", 1, 0.0)
    assert not permit.accept(reply(config, "go", 2), "f2", 2, 0.0)
    assert outputs[-1] == ("halt",)
    assert permit.reason == "avoidance_capture_pending"


def test_runner_rotation_submits_zero_forward_and_curved_motion_keeps_forward(monkeypatch, tmp_path):
    from navigation_runner_fixtures import isolated as fixture

    from apps.compute.navigation import NavigationRunner

    setup = fixture.__wrapped__(monkeypatch, tmp_path)
    runner = NavigationRunner(clock=lambda: 0.0)
    runner.policy = guided("auto")
    runner.lease.deadline = 0.3
    monkeypatch.setattr(runner, "_authority", lambda: True)
    runner.turn("right", 0.1)
    assert setup[-1][-1]["vx"] == 0.0
    assert setup[-1][-1]["yaw"] < 0
    runner.steer("left", 0.1)
    assert setup[-1][-1]["vx"] == runner.policy["speed"]
    assert setup[-1][-1]["yaw"] > 0


@pytest.mark.parametrize("capability", [None, False, 1])
def test_guidance_capability_must_be_explicit_on_host(capability):
    from apps.compute.client import ComputeError
    from services.axis_guidance import require_host

    with pytest.raises(ComputeError, match="navigation_guidance_update_required"):
        require_host({"axis_guidance_v1": capability}, 1)


def test_preparation_options_include_both_collision_and_guidance_contracts():
    from services.collision_geometry import preparation_options

    assert preparation_options(guided()) == {"collision_geometry_version": 1, "axis_guidance_version": 1}


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("supported", [False, True])
def test_stream_preparation_checks_guidance_before_accepting_host(monkeypatch, native, supported):
    from apps.compute import stream_prepare
    from apps.compute.client import ComputeError
    from services.collision_geometry import preparation_options

    requests, ready = [], []
    monkeypatch.setattr(stream_prepare, "native", lambda: native)
    monkeypatch.setattr(stream_prepare, "snapshot", lambda: {})
    selection = {"device_id": "offline", "token": "test-token"}
    monkeypatch.setattr(
        stream_prepare, "_stream_setup", lambda *args, **kwargs: (selection, object(), "http://127.0.0.1")
    )
    monkeypatch.setattr(stream_prepare, "_fresh_local_source", lambda *args: {})

    def read(opener, req, *args):
        requests.append(req.full_url)
        return {"collision_geometry_v1": True, "axis_guidance_v1": supported}

    def accept(*args):
        ready.append(True)
        return {"ready": True}

    monkeypatch.setattr(stream_prepare, "_read_stream_status", read)
    monkeypatch.setattr(stream_prepare, "_ready_stream", accept)
    options = {**preparation_options(guided()), "opener": object(), "clock": lambda: 0.0}
    if supported:
        result = stream_prepare.prepare_stream(**options)
        assert result == ({"ready": True} if native else None)
        assert ready == ([True] if native else [])
    else:
        with pytest.raises(ComputeError, match="navigation_guidance_update_required"):
            stream_prepare.prepare_stream(**options)
        assert not ready
    assert len(requests) == 1
    assert requests[0].endswith("/vision/status?stream=true" if native else "/vision/status")


def test_rotation_drive_crop_cannot_omit_calibrated_body_space():
    config = guided()
    config["perception"]["input_region"] = {"version": 1, "bounds": [0.35, 0.65, 0.65, 0.95]}
    with pytest.raises(ValueError, match="navigation_rotation_input_incomplete"):
        navigation_config.validate(config)
