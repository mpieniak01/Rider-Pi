"""Targeted intervention crosses only its own pending resume, never another epoch."""

import pytest
from motion_fakes import command, executor as executor
from test_operator_control_lifecycle import arm_navigation, move, operator


def pending_resume(instance, clock):
    arm_navigation(instance)
    instance.apply(operator(instance))
    origin = instance.gate.generation
    clock.now += 0.001
    assert instance.apply(operator(instance, "navigation_resume", request_id="resume", seq=4))["status"] == "executed"
    clock.now += 0.001
    assert (
        instance.apply(
            command(instance, source="navigation", execution_context="panel", operator_operation_id="resume", seq=100)
        )["status"]
        == "accepted"
    )
    return origin


@pytest.mark.parametrize("origin_known", [True, False])
def test_operator_sequence_does_not_race_navigation_and_can_cancel_pending_ack(executor, origin_known):
    instance, clock = executor
    origin = pending_resume(instance, clock)
    generation = origin if origin_known else instance.gate.generation
    clock.now += 0.001
    correction = move(
        instance,
        intervene=True,
        generation=generation,
        seq=5,
        request_id="correction",
        supersedes_operation_id="resume",
    )
    ack = instance.apply(correction)
    assert ack["status"] == "accepted"
    assert ack["command_generation"] == generation
    assert instance.gate.generation not in {origin, generation}
    assert instance.gate.owner == "manual"
    assert instance.gate.last_seq == 5
    assert instance.controller.t_lx < 0
    assert instance.apply(correction)["operator_replay"] is True


@pytest.mark.parametrize(
    "updates",
    [
        {"supersedes_operation_id": "other"},
        {"panel_id": "foreign"},
        {"seq": 4},
        {"ts": 999.0},
        {"intervene": False},
    ],
)
def test_targeted_origin_exception_rejects_wrong_target_panel_sequence_or_ttl(executor, updates):
    instance, clock = executor
    origin = pending_resume(instance, clock)
    current = instance.gate.generation
    clock.now += 0.001
    correction = move(
        instance,
        **{
            "intervene": True,
            "generation": origin,
            "seq": 5,
            "supersedes_operation_id": "resume",
            **updates,
        },
    )
    assert instance.apply(correction)["status"] == "rejected"
    assert instance.gate.generation == current
    assert instance.gate.owner == "navigation"
    assert instance.controller.t_lx > 0


def test_global_stop_revokes_targeted_origin_exception(executor):
    instance, clock = executor
    origin = pending_resume(instance, clock)
    instance.apply({"action": "stop"})
    current = instance.gate.generation
    assert (
        instance.apply(operator(instance, generation=origin, seq=5, supersedes_operation_id="resume"))["status"]
        == "rejected"
    )
    assert instance.gate.generation == current
    assert instance.gate.state == "DISARMED"


def test_initial_trial_also_preserves_operator_sequence_namespace(executor):
    instance, clock = executor
    arm_navigation(instance)
    generation = instance.gate.generation
    instance.apply(
        command(instance, source="navigation", execution_context="panel", operator_operation_id="trial-arm", seq=100)
    )
    clock.now += 0.001
    ack = instance.apply(
        move(instance, intervene=True, generation=generation, seq=1, supersedes_operation_id="trial-arm")
    )
    assert ack["status"] == "accepted"
    assert instance.gate.last_seq == 1
    assert instance.gate.owner == "manual"


@pytest.mark.parametrize("generation", [[], {}])
def test_malformed_targeted_bus_generation_rejects_without_mutation(executor, generation):
    instance, clock = executor
    pending_resume(instance, clock)
    before = instance.gate.generation
    clock.now += 0.001
    ack = instance.apply(move(instance, intervene=True, generation=generation, seq=5, supersedes_operation_id="resume"))
    assert ack["status"] == "rejected"
    assert instance.gate.generation == before
    assert instance.gate.owner == "navigation"


def test_malformed_request_id_never_crashes_ack_ledger(executor):
    instance, _ = executor
    arm_navigation(instance)
    assert instance.apply(operator(instance, request_id=[]))["status"] == "rejected"
