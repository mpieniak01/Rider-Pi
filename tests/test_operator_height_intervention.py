"""Height Apply through the real executor with an in-memory adapter only."""

import pytest
from journey_fakes import arm, goal
from motion_fakes import command, executor as executor
from test_operator_direction_intervention import gesture


def height_intent(instance, height=95, **changes):
    row = command(
        instance,
        action="height",
        height=height,
        panel_id="height-panel",
        execution_context="panel",
        owner="manual",
        arming_mode="operator",
        operator_consent=True,
        operator_plan=f"Set height {height} SDK",
        operator_intervention_version=1,
        intervene=True,
        device_settings=True,
    )
    for key in ("vx", "yaw", "duration"):
        row.pop(key)
    row.update(changes)
    return row


@pytest.mark.parametrize("initial", ["disarmed", "manual", "journey"])
@pytest.mark.parametrize("height", [75, 95, 115])
def test_one_height_apply_stops_previous_goal_before_pose(executor, initial, height):
    instance, clock = executor
    if initial == "journey":
        arm(instance)
        instance.apply(goal(instance, clock))
    elif initial == "manual":
        instance.apply(gesture(instance))
    instance.tick(0.01)
    generation = instance.gate.generation
    start = len(instance.adapter.calls)
    original = height_intent(instance, height)
    result = instance.apply(original)
    assert result["status"] == "executed"
    assert result["reason"] == "sdk_accepted"
    assert instance.gate.generation != generation
    assert instance.gate.owner == "manual"
    assert instance.gate.panel_id == "height-panel"
    assert not instance.gate.journey.active
    assert instance.controller.stopped
    assert instance.pending is None
    events = instance.adapter.calls[start:]
    assert events[-1] == ("height", height)
    assert ("stop",) in events[:-1]
    instance.tick(0.01)
    assert not any(event[0] == "move" and any(event[1:]) for event in instance.adapter.calls[start:])
    assert instance.snapshot()["actuators"]["height"]["value"] == height
    assert instance.snapshot()["operator_height_intervention_version"] == 1
    instance.apply(original)
    assert instance.adapter.calls.count(("height", height)) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"height": 74},
        {"height": 116},
        {"height": True},
        {"height": 90.0},
        {"mode": "release"},
        {"direction": "forward"},
        {"vx": 0.5},
        {"operator_consent": False},
        {"operator_intervention_version": True},
        {"ts": 0},
        {"generation": "stale"},
        {"settings_revision": -1},
    ],
)
def test_invalid_height_cannot_grant_authority_or_set_pose(executor, changes):
    instance, _ = executor
    generation = instance.gate.generation
    result = instance.apply(height_intent(instance, **changes))
    assert result["status"] == "rejected"
    assert instance.gate.state == "DISARMED"
    assert instance.gate.generation == generation
    assert not any(event[0] == "height" for event in instance.adapter.calls)


def test_stop_and_estop_reject_an_earlier_height_apply(executor):
    instance, _ = executor
    delayed = height_intent(instance)
    instance.apply({"action": "stop"})
    assert instance.apply(delayed)["status"] == "rejected"
    instance.apply({"action": "estop"})
    assert instance.apply(height_intent(instance))["reason"] == "estop_latched"
    assert instance.gate.state == "ESTOP"
    assert not any(event[0] == "height" for event in instance.adapter.calls)


def test_legacy_height_still_requires_arm(executor):
    instance, _ = executor
    row = height_intent(instance)
    for key in ("operator_intervention_version", "intervene"):
        row.pop(key)
    assert instance.apply(row)["reason"] == "motion_disarmed"


def test_failed_height_does_not_leave_motion_armed(executor):
    instance, _ = executor
    instance.adapter.set_height = lambda value: False
    result = instance.apply(height_intent(instance))
    assert result["status"] == "rejected"
    assert instance.gate.state == "DISARMED"
    assert instance.controller.stopped


@pytest.mark.parametrize("enabled", [True, False])
def test_explicit_balance_apply_stops_drive_and_transfers_authority(executor, enabled):
    instance, _ = executor
    instance.apply(gesture(instance))
    instance.tick(0.01)
    row = height_intent(instance)
    row.pop("height")
    row.update(action="balance", enabled=enabled)
    start = len(instance.adapter.calls)
    result = instance.apply(row)
    assert result["status"] == "executed"
    assert instance.gate.owner == "manual"
    assert instance.gate.panel_id == "height-panel"
    assert instance.controller.stopped
    assert instance.adapter.calls[start:][-1] == ("balance", enabled)
    assert ("stop",) in instance.adapter.calls[start:-1]
    assert instance.snapshot()["operator_posture_intervention_version"] == 1


@pytest.mark.parametrize("enabled", [0, 1, None, "true"])
def test_balance_gesture_requires_strict_boolean(executor, enabled):
    instance, _ = executor
    row = height_intent(instance)
    row.pop("height")
    row.update(action="balance", enabled=enabled)
    assert instance.apply(row)["status"] == "rejected"
    assert instance.gate.state == "DISARMED"
    assert not any(event[0] == "balance" for event in instance.adapter.calls)
