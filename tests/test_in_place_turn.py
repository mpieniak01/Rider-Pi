"""In-place commands use the normal executor, fake SDK and original TTL."""

import pytest
from motion_fakes import arm, command, executor as executor
from test_held_motion import advance, intent
from test_manual_settings import operator_arm

from apps.motion.actuator_contract import validate_actuator


@pytest.mark.parametrize("direction,sign", [("left", -1), ("right", 1)])
@pytest.mark.parametrize("mode", ["pulse", "hold"])
def test_in_place_turn_from_forward_motion_brakes_before_yaw(executor, direction, sign, mode):
    """Verify in place turn from forward motion brakes before yaw."""
    instance, clock = executor
    operator_arm(instance)
    instance.apply(intent(instance))
    advance(instance, clock, 0.16)
    assert instance.controller.o_lx > 0
    generation = instance.gate.generation
    ack = instance.apply(intent(instance, mode, direction, turn_mode="in_place"))
    assert ack["requested"]["turn_mode"] == "in_place"
    previous = instance.controller.o_lx
    for _ in range(25):
        clock.now += 0.02
        instance.poll_sensors()
        instance.tick(0.02)
        if instance.controller.o_lx != 0:
            assert instance.controller.o_lx <= previous
            assert instance.controller.o_az == 0
        else:
            break
        previous = instance.controller.o_lx
    assert instance.controller.o_lx == 0
    advance(instance, clock, 0.04)
    assert instance.controller.o_az * sign > 0
    instance.apply(intent(instance, "release", direction, turn_mode="in_place"))
    advance(instance, clock, 0.52)
    assert instance.controller.stopped
    assert instance.gate.generation == generation
    assert instance.gate.state == "ARMED"


def test_in_place_turn_expiry_cannot_restart_without_new_intent(executor):
    """Verify in place turn expiry cannot restart without new intent."""
    instance, clock = executor
    operator_arm(instance)
    instance.apply(intent(instance, "hold", "left", turn_mode="in_place"))
    advance(instance, clock, 0.6)
    assert instance.controller.stopped
    assert instance.controller.o_lx == instance.controller.o_az == 0


@pytest.mark.parametrize(
    "change",
    [
        {"turn_mode": "unknown"},
        {"direction": "forward"},
        {"source": "navigation"},
        {"execution_context": "agent"},
        {"device_settings": False},
        {"turn_mode": True},
    ],
)
def test_in_place_turn_scope_is_validated(change):
    """Verify in place turn scope is validated."""
    command = {
        "action": "move",
        "source": "manual",
        "execution_context": "panel",
        "device_settings": True,
        "direction": "left",
        "turn_mode": "in_place",
        "vx": 0,
        "yaw": -0.2,
        "duration": 0.2,
    }
    with pytest.raises(ValueError, match="invalid_turn_mode"):
        validate_actuator({**command, **change})


@pytest.mark.parametrize("action", ["stop", "disarm", "estop"])
@pytest.mark.parametrize("turn_mode", ["in_place", "obsolete", True])
def test_stop_ignores_inherited_turn_metadata(executor, action, turn_mode):
    """Verify stop ignores inherited turn metadata."""
    instance, clock = executor
    operator_arm(instance)
    instance.apply(intent(instance))
    advance(instance, clock, 0.12)
    assert instance.controller.o_lx > 0
    ack = instance.apply(command(instance, action, turn_mode=turn_mode))
    assert ack["status"] == "executed"
    assert instance.controller.stopped
    assert instance.controller.o_lx == instance.controller.o_az == 0


def test_timed_manual_pulse_turns_with_original_watchdog(executor):
    """Verify timed manual pulse turns with original watchdog."""
    instance, clock = executor
    assert arm(instance, execution_context="panel")["status"] == "executed"
    assert instance.gate.arming_mode == "timed"
    payload = intent(instance, "pulse", "left", turn_mode="in_place")
    ack = instance.apply(payload)
    assert ack["status"] == "accepted"
    deadline = instance.controller.deadline
    assert deadline <= clock.now + instance.controller.limits.watchdog_s
    advance(instance, clock, 0.04)
    assert instance.controller.o_lx == 0 and instance.controller.o_az < 0
    advance(instance, clock, 0.52)
    assert instance.controller.stopped
