"""Explicit direction transfer and reorderings through the real isolated executor."""

import pytest
from journey_fakes import arm, goal
from motion_fakes import command, executor as executor


def gesture(instance, **changes):
    fields = {
        "request_id": "new-direction",
        "source": "manual",
        "owner": "manual",
        "execution_context": "panel",
        "arming_mode": "operator",
        "panel_id": "operator",
        "intervene": True,
        "operator_intervention_version": 1,
        "operator_consent": True,
        "operator_plan": "Operator direction gesture with saved manual limits",
        "device_settings": True,
        "direction": "forward",
    }
    fields.update(changes)
    body = command(instance, **fields)
    for key in ("vx", "yaw", "duration"):
        body.pop(key, None)
    return body


def release(instance, original, **changes):
    row = gesture(instance, request_id="release", mode="release")
    row.update(generation=original["generation"], supersedes_operation_id=original["request_id"])
    row.pop("operator_consent")
    row.pop("operator_plan")
    row.update(changes)
    return row


@pytest.mark.parametrize("initial", ["disarmed", "journey", "failed"])
def test_fresh_direction_is_one_transaction_without_separate_arm(executor, initial):
    instance, clock = executor
    if initial != "disarmed":
        arm(instance)
        instance.apply(goal(instance, clock))
        if initial == "failed":
            instance.gate.disarm("decision_timeout")
            instance.tick(0.01)
    old_generation = instance.gate.generation
    original = gesture(instance)
    result = instance.apply(original)
    assert result["status"] == "accepted"
    assert instance.gate.state == "ARMED"
    assert instance.gate.owner == "manual"
    assert instance.gate.arming_mode == "operator"
    assert instance.gate.generation != old_generation
    assert instance.gate.panel_id == "operator"
    assert instance.gate.operator_control.snapshot()["operation_id"] == original["request_id"]
    assert instance.gate.operator_control.enabled is False
    assert not instance.gate.journey.active
    instance.tick(0.01)
    assert instance.gate.owner == "manual"
    assert instance.snapshot()["operator_intervention_version"] == 1


def test_cancel_before_dispatch_tombstone_never_grants_or_moves(executor):
    instance, _ = executor
    original = gesture(instance)
    assert instance.apply(release(instance, original))["status"] == "executed"
    assert instance.apply(original)["reason"] in {"operator_intervention_cancelled", "stale_generation"}
    assert instance.gate.state == "DISARMED"
    assert instance.controller.stopped


def test_release_after_ack_uses_original_generation_and_zeros_only_matching_owner(executor):
    instance, _ = executor
    original = gesture(instance)
    instance.apply(original)
    instance.tick(0.01)
    reply = instance.apply(release(instance, original))
    assert reply["status"] == "executed"
    assert reply["hardware_stop_sent"] is True
    assert instance.controller.stopped
    assert instance.gate.owner == "manual"
    assert instance.gate.arming_mode == "operator"


def test_old_release_and_old_journey_stop_cannot_interrupt_new_direction(executor):
    instance, clock = executor
    arm(instance)
    instance.apply(goal(instance, clock))
    old_generation = instance.gate.generation
    first = gesture(instance)
    instance.apply(first)
    second = gesture(instance, request_id="newer-direction", direction="left")
    instance.apply(second)
    generation = instance.gate.generation
    assert instance.apply(release(instance, first))["status"] == "rejected"
    assert instance.apply({"action": "stop", "expected_generation": old_generation})["status"] == "rejected"
    assert instance.gate.generation == generation
    assert instance.gate.owner == "manual"


@pytest.mark.parametrize(
    "change", [{"operator_consent": False}, {"operator_intervention_version": True}, {"ts": 0}, {"generation": "stale"}]
)
def test_invalid_gesture_does_not_change_authority(executor, change):
    instance, _ = executor
    generation = instance.gate.generation
    assert instance.apply(gesture(instance, **change))["status"] == "rejected"
    assert instance.gate.generation == generation
    assert instance.gate.state == "DISARMED"


def test_estop_never_cleared_by_direction_or_release(executor):
    instance, _ = executor
    instance.apply({"action": "estop"})
    original = gesture(instance)
    assert instance.apply(original)["reason"] == "estop_latched"
    instance.apply(release(instance, original))
    assert instance.gate.state == "ESTOP"
    assert instance.controller.stopped


def test_new_panel_explicit_gesture_revokes_other_panel_and_late_commands(executor):
    instance, _ = executor
    first = gesture(instance)
    instance.apply(first)
    second = gesture(instance, request_id="new-panel-direction", panel_id="other")
    assert instance.apply(second)["status"] == "accepted"
    assert instance.gate.panel_id == "other"
    assert instance.apply(first)["status"] == "rejected"
    assert instance.apply(release(instance, first))["status"] == "rejected"


@pytest.mark.parametrize("delivered_first", [True, False])
def test_release_of_intervention_cancels_old_navigation_in_either_delivery_order(executor, delivered_first):
    instance, clock = executor
    arm(instance)
    instance.apply(goal(instance, clock))
    original = gesture(instance, supersedes_operation_id="mission")
    cancel = release(instance, original, supersedes_navigation_operation_id="mission")
    if not delivered_first:
        instance.apply(original)
    assert instance.apply(cancel)["status"] == "executed"
    instance.apply(original)
    assert instance.controller.stopped
    assert not instance.gate.journey.active
    assert instance.gate.owner != "navigation"


def test_duplicate_release_cannot_cancel_newer_manual_goal_or_preparation(executor):
    instance, clock = executor
    original = gesture(instance)
    cancel = release(instance, original)
    instance.apply(original)
    instance.apply(cancel)
    clock.now += 0.01
    following = command(
        instance, request_id="normal-following-direction", panel_id="operator", execution_context="panel"
    )
    assert instance.apply(following)["status"] == "accepted"
    generation = instance.gate.generation
    assert instance.apply(cancel)["status"] == "executed"
    assert instance.gate.generation == generation
    assert instance.pending["request_id"] == following["request_id"]


def test_unarmed_preparation_is_invalidated_by_cancel_without_granting_authority(executor):
    instance, _ = executor
    original = gesture(instance)
    origin = instance.gate.generation
    cancel = release(instance, original, supersedes_navigation_operation_id="preparing-journey")
    assert instance.apply(cancel)["status"] == "executed"
    generation = instance.gate.generation
    assert generation != origin
    assert instance.gate.state == "DISARMED"
    assert instance.gate.owner is None
    assert instance.apply(cancel)["status"] == "executed"
    assert instance.gate.generation == generation
    assert instance.apply(original)["status"] == "rejected"
    assert instance.controller.stopped


def test_other_panel_cancel_tombstone_cannot_consume_a_direction_for_another_panel(executor):
    instance, _ = executor
    first = gesture(instance)
    instance.apply(first)
    following = gesture(instance, request_id="pending-direction", panel_id="other")
    cancel = release(instance, following, panel_id="operator")
    # Unmatched release stores only its own panel/origin scope and stops nothing.
    assert instance.apply(cancel)["status"] == "executed"
    assert instance.apply(following)["status"] == "accepted"
    assert instance.gate.panel_id == "other"


@pytest.mark.parametrize("cancel_first", [True, False])
def test_preparing_origin_release_is_scoped_across_new_navigation_generation(executor, cancel_first):
    instance, _ = executor
    origin = instance.gate.generation
    # Preparation retires an earlier session before obtaining the new journey ARM.
    instance.apply({"action": "stop"})
    arm(instance, operator_origin_generation=origin, journey_id="new-mission")
    assert instance.gate.generation != origin
    original = gesture(instance, generation=origin, supersedes_operation_id="new-mission", seq=1)
    cancel = release(instance, original, supersedes_navigation_operation_id="new-mission", seq=2)
    if not cancel_first:
        assert instance.apply(original)["status"] == "accepted"
    assert instance.apply(cancel)["status"] == "executed"
    assert instance.controller.stopped
    assert not instance.gate.journey.active
    assert instance.gate.owner != "navigation"
    assert instance.apply(original)["status"] == "rejected"


def test_origin_of_different_preparation_cannot_revoke_new_journey(executor):
    instance, _ = executor
    origin = instance.gate.generation
    instance.apply({"action": "stop"})
    arm(instance, operator_origin_generation=origin, journey_id="new-mission")
    original = gesture(instance, generation=origin, supersedes_operation_id="old-mission", seq=1)
    cancel = release(instance, original, supersedes_navigation_operation_id="old-mission", seq=2)
    generation = instance.gate.generation
    assert instance.apply(cancel)["status"] == "rejected"
    assert instance.gate.generation == generation
    assert instance.gate.journey.active is True
