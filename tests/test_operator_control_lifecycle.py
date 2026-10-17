"""Operator arbitration is exercised with memory-only actuator fixtures."""

import uuid

import pytest
from motion_fakes import command, executor as executor


def arm_navigation(instance, **updates):
    return instance.apply(
        command(
            instance,
            "arm",
            owner="navigation",
            arming_mode="timed",
            lease_s=10,
            operator_consent=True,
            operator_plan="Isolated warm lifecycle",
            execution_context="panel",
            panel_id="operator",
            operator_control_version=1,
            request_id="trial-arm",
            **updates,
        )
    )


def operator(instance, action="navigation_pause", **updates):
    return command(
        instance,
        action,
        **{"panel_id": "operator", "execution_context": "panel", "request_id": uuid.uuid4().hex, **updates},
    )


def move(instance, **updates):
    row = operator(instance, "move", device_settings=True, direction="backward", **updates)
    for key in ("vx", "yaw", "duration"):
        row.pop(key, None)
    return row


def test_intervention_retires_generation_and_preserves_timed_consent(executor):
    instance, _ = executor
    assert arm_navigation(instance)["status"] == "executed"
    deadline, old_generation = instance.gate.lease_deadline, instance.gate.generation
    old = command(instance, source="navigation", execution_context="panel", operator_operation_id="trial-arm")
    assert instance.apply(old)["status"] == "accepted"
    takeover = move(instance, intervene=True, request_id="correction")
    assert instance.apply(takeover)["status"] == "accepted"
    state = instance.snapshot()
    assert state["generation"] != old_generation
    assert state["owner"] == "manual"
    assert state["operator_control"]["state"] == "paused"
    assert state["panel_control"]["holder"] == "operator"
    assert instance.gate.lease_deadline == deadline
    assert instance.gate.arming_mode == "timed"
    assert instance.controller.t_lx < 0
    assert instance.apply(old)["reason"] == "stale_generation"
    assert instance.controller.t_lx < 0


def test_pending_resume_cannot_survive_pause_or_scoped_old_stop(executor):
    instance, _ = executor
    arm_navigation(instance)
    instance.apply(operator(instance))
    assert instance.apply(operator(instance, "navigation_resume", request_id="resume"))["status"] == "executed"
    resume_generation = instance.gate.generation
    assert instance.gate.operator_control.state == "qualifying"
    late = command(instance, source="navigation", execution_context="panel", operator_operation_id="resume")
    assert instance.apply(operator(instance, request_id="pause"))["status"] == "executed"
    assert instance.apply(late)["reason"] == "stale_generation"
    assert (
        instance.apply({"action": "stop", "expected_generation": resume_generation})["reason"]
        == "stale_stop_generation"
    )
    assert instance.gate.owner == "manual"


@pytest.mark.parametrize("action", ["navigation_pause", "navigation_resume"])
def test_foreign_or_stale_panel_cannot_transfer_authority(executor, action):
    instance, _ = executor
    arm_navigation(instance)
    original = instance.gate.generation
    assert instance.apply(operator(instance, action, panel_id="foreign"))["reason"] == "panel_owner_mismatch"
    assert instance.apply(operator(instance, action, generation="old"))["reason"] == "stale_generation"
    assert instance.gate.generation == original
    assert instance.gate.owner == "navigation"


def test_expired_lease_stop_and_estop_never_rearmed_by_resume(executor):
    instance, clock = executor
    arm_navigation(instance)
    instance.apply(operator(instance))
    clock.now += 11
    assert instance.apply(operator(instance, "navigation_resume"))["status"] == "rejected"
    assert instance.gate.state == "DISARMED"
    assert instance.apply({"action": "estop"})["status"] == "executed"
    assert instance.apply(operator(instance, "navigation_resume"))["status"] == "rejected"
    assert instance.gate.state == "ESTOP"


def test_manual_requires_explicit_intervene_and_settings_revision(executor):
    instance, _ = executor
    arm_navigation(instance)
    assert instance.apply(move(instance))["reason"] == "owner_mismatch"
    # Invalid settings must not transfer the navigation owner.
    assert instance.apply(move(instance, intervene=True, settings_revision=999))["reason"] == "manual_settings_stale"
    assert instance.gate.owner == "navigation"


def test_resume_cannot_extend_lease_or_replay_old_operation(executor):
    instance, _ = executor
    arm_navigation(instance)
    instance.apply(operator(instance))
    deadline = instance.gate.lease_deadline
    result = instance.apply(operator(instance, "navigation_resume", request_id="new"))
    assert result["status"] == "executed"
    assert instance.gate.lease_deadline == deadline
    instance.gate.clock.now += 0.001
    old = command(instance, source="navigation", execution_context="panel", operator_operation_id="old")
    assert instance.apply(old)["reason"] == "navigation_operation_stale"
    assert instance.controller.stopped


def test_same_resume_request_is_idempotent_and_cannot_extend_consent(executor):
    instance, _ = executor
    arm_navigation(instance)
    instance.apply(operator(instance))
    body = operator(instance, "navigation_resume", request_id="idempotent")
    first = instance.apply(body)
    generation, deadline = instance.gate.generation, instance.gate.lease_deadline
    second = instance.apply(body)
    assert first["status"] == second["status"] == "executed"
    assert second["operator_replay"] is True
    assert instance.gate.generation == generation
    assert instance.gate.lease_deadline == deadline
    assert instance.apply({**body, "seq": body["seq"] + 1})["reason"] == "operator_request_conflict"


def test_intervention_replay_does_not_repeat_sdk_or_change_generation(executor):
    instance, clock = executor
    arm_navigation(instance)
    clock.now += 0.001
    body = move(instance, intervene=True, request_id="one-correction")
    first = instance.apply(body)
    generation = instance.gate.generation
    sdk = list(instance.adapter.calls)
    second = instance.apply(body)
    assert first["status"] == second["status"] == "accepted"
    assert instance.gate.generation == generation
    assert instance.adapter.calls == sdk


@pytest.mark.parametrize(
    "overrides",
    [
        {"owner": "manual", "arming_mode": "operator"},
        {"lease_s": 11},
    ],
)
def test_optin_never_converts_unbounded_manual_or_long_lease_to_navigation(executor, overrides):
    instance, _ = executor
    row = command(
        instance,
        "arm",
        **{
            "owner": "navigation",
            "arming_mode": "timed",
            "lease_s": 10,
            "operator_consent": True,
            "operator_plan": "Bounded navigation only",
            "execution_context": "panel",
            "panel_id": "operator",
            "operator_control_version": 1,
            **overrides,
        },
    )
    if row["arming_mode"] == "operator":
        row.pop("lease_s")
    assert instance.apply(row)["status"] == "rejected"
    assert instance.gate.state == "DISARMED"


def test_replayed_old_ack_never_advertises_newer_generation(executor):
    instance, _ = executor
    arm_navigation(instance)
    pause = operator(instance)
    original = instance.apply(pause)
    instance.apply({"action": "stop"})
    replay = instance.apply(pause)
    assert replay["generation"] == original["generation"]
    assert replay["generation"] != instance.gate.generation
    assert instance.gate.state == "DISARMED"


def test_manual_correction_expires_with_original_navigation_consent(executor):
    instance, clock = executor
    arm_navigation(instance)
    clock.now += 0.001
    assert instance.apply(move(instance, intervene=True))["status"] == "accepted"
    clock.now += 11
    instance.tick(0.02)
    assert instance.gate.state == "DISARMED"
    assert instance.gate.reason == "consent_expired"
    assert instance.controller.stopped
