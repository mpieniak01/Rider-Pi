"""Domain-level scoped cleanup using the existing fake systemd and real gate."""

from test_camera_pipeline import CAPS, command as camera_command, isolated_paths as isolated_paths
from test_navigation_trial import world as world

from services.camera_pipeline import CameraPipeline


def scoped(world):
    world.manager.safety_scoped_stop = lambda owner, generation: world.submit(
        {
            "action": "stop",
            "source": owner,
            "expected_generation": generation,
        }
    )[0]


def control(world, action, **updates):
    safety = world.safety()
    return world.submit(
        {
            "action": action,
            "source": "manual",
            "execution_context": "panel",
            "panel_id": "operator",
            "request_id": action,
            "generation": safety["generation"],
            "seq": safety["last_seq"] + 1,
            "ts": world.gate.wall_clock(),
            "ttl_ms": 500,
            **updates,
        }
    )


def test_explicit_s14_stop_after_resume_targets_new_generation(world):
    world.trial.start(world.body(operator_control_version=1, panel_id="operator"))
    scoped(world)
    assert control(world, "navigation_pause")[1] == 200
    assert control(world, "navigation_resume")[1] == 200
    resumed = world.gate.generation
    result = world.manager.set_feature("s14_venom_navigation", False)
    assert result["ok"]
    assert world.gate.state == "DISARMED"
    assert world.commands[-1]["expected_generation"] == resumed


def test_old_s14_cleanup_preserves_manual_authority(world):
    world.trial.start(world.body(operator_control_version=1, panel_id="operator"))
    scoped(world)
    assert control(world, "navigation_pause")[1] == 200
    manual = world.gate.generation
    before = list(world.commands)
    assert world.manager.set_feature("s14_venom_navigation", False)["ok"]
    assert world.gate.state == "ARMED" and world.gate.owner == "manual"
    assert world.gate.generation == manual
    assert world.commands == before


def test_camera_preemption_then_manual_arm_same_generation_is_preserved(world):
    world.trial.start(world.body(operator_control_version=1, panel_id="operator"))
    original_safety = world.manager.safety_status
    world.manager.safety_status = lambda: {**original_safety(), "moving": False, "output": {"lx": 0, "az": 0}}
    stops = []

    def stop(owner, expected_generation):
        result, status = world.submit({"action": "stop", "source": owner, "expected_generation": expected_generation})
        assert status == 200
        stops.append(expected_generation)
        # A new manual ARM can retain the post-STOP generation.
        assert world.arm_manual()[1] == 200
        return result

    pipeline = CameraPipeline(world.manager, capability_fn=lambda: CAPS, stopper=stop)
    _, status = pipeline.execute(camera_command("stop"))
    assert status == 200
    assert len(stops) == 1
    assert world.gate.state == "ARMED" and world.gate.owner == "manual"
    assert sum(row["action"] == "stop" for row in world.commands) == 1
