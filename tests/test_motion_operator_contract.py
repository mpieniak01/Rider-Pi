"""Isolated executor/SDK contract tests: no real SDK, sockets or robot address."""

from __future__ import annotations

import json
import time

import pytest
from motion_fakes import FakeAdapter, FakeSDK, arm, command, executor as executor

from apps.motion.executor import MotionExecutor
from apps.motion.sensor_reader import project_sensor_payload
from apps.safety import estop
from apps.safety.gate import MotionGate
from apps.safety.state import read_status, write_status
from drivers.xgo.adapter import XgoAdapter, uart_inventory


def test_panel_permission_cannot_authorize_physical_test_commands(executor):
    instance, _ = executor
    arm(instance)
    snapshot = instance.snapshot()
    assert snapshot["panel_motion_enabled"] is True
    assert snapshot["test_motion_enabled"] is False
    before = list(instance.adapter.calls)
    denied = instance.apply(command(instance, execution_context="test"))
    assert denied["reason"] == "test_operator_consent_required"
    denied = instance.apply(command(instance, execution_context="test", test_operator_consent=True))
    assert denied["reason"] == "execution_context_mismatch"
    assert instance.adapter.calls == before


def test_test_permission_is_separate_and_every_attempt_requires_operator_consent(executor):
    instance, _ = executor
    denied = instance.apply(
        command(
            instance,
            "arm",
            owner="manual",
            operator_consent=True,
            operator_plan="Prepared isolated test",
            lease_s=5,
            execution_context="test",
        )
    )
    assert denied["reason"] == "test_operator_consent_required"
    allowed = instance.apply(
        command(
            instance,
            "arm",
            owner="manual",
            operator_consent=True,
            test_operator_consent=True,
            operator_plan="Prepared isolated test",
            lease_s=5,
            execution_context="test",
        )
    )
    assert allowed["status"] == "executed"
    snapshot = instance.snapshot()
    assert snapshot["test_motion_enabled"] is True
    assert snapshot["panel_motion_enabled"] is False
    assert instance.apply(command(instance))["reason"] == "execution_context_mismatch"
    assert instance.apply(command(instance, execution_context="test"))["reason"] == "test_operator_consent_required"
    assert (
        instance.apply(command(instance, execution_context="test", test_operator_consent=True))["status"] == "accepted"
    )
    instance.apply({"action": "stop"})
    assert instance.snapshot()["test_motion_enabled"] is False
    assert instance.snapshot()["panel_motion_enabled"] is False


def test_unknown_test_context_is_rejected_without_hardware(executor):
    instance, _ = executor
    arm(instance)
    for context in (None, {}, [], True, "automatic"):
        assert instance.apply(command(instance, execution_context=context))["reason"] == "unknown_execution_context"


def test_operator_panel_arming_has_no_time_expiry_and_stop_revokes_it(executor):
    instance, clock = executor
    result = instance.apply(
        command(
            instance,
            "arm",
            owner="manual",
            operator_consent=True,
            operator_plan="Operator controlled session",
            execution_context="panel",
            arming_mode="operator",
        )
    )
    assert result["status"] == "executed"
    clock.now += 3600
    instance.gate.poll()
    assert instance.gate.can_actuate() is True
    snapshot = instance.gate.snapshot()
    assert snapshot["state"] == "ARMED"
    assert snapshot["arming_mode"] == "operator"
    assert snapshot["lease_remaining_s"] is None
    assert snapshot["panel_motion_enabled"] is True
    instance.apply({"action": "stop"})
    assert instance.gate.snapshot()["panel_motion_enabled"] is False


def test_test_session_cannot_request_operator_controlled_unlimited_arming(executor):
    instance, _ = executor
    result = instance.apply(
        command(
            instance,
            "arm",
            owner="manual",
            operator_consent=True,
            test_operator_consent=True,
            operator_plan="Isolated test session",
            execution_context="test",
            arming_mode="operator",
        )
    )
    assert result["reason"] == "operator_arming_panel_only"


def test_status_read_supports_operator_arming_but_still_expires_stale_data(executor, monkeypatch):
    instance, clock = executor
    instance.apply(
        command(
            instance,
            "arm",
            owner="manual",
            operator_consent=True,
            operator_plan="Operator controlled session",
            execution_context="panel",
            arming_mode="operator",
        )
    )
    state = instance.snapshot()
    write_status(state)
    monkeypatch.setattr("apps.safety.state.time.time", lambda: clock.now + 1)
    assert read_status()["can_move"] is True
    assert read_status()["panel_motion_enabled"] is True
    monkeypatch.setattr("apps.safety.state.time.time", lambda: clock.now + 4)
    assert read_status()["can_move"] is False


@pytest.mark.parametrize("dispatch_after_expiry", [False, True])
def test_operator_pulse_stops_without_disarming_and_next_click_works(executor, dispatch_after_expiry):
    instance, clock = executor
    instance.apply(
        command(
            instance,
            "arm",
            owner="manual",
            operator_consent=True,
            operator_plan="Mock operator session",
            execution_context="panel",
            arming_mode="operator",
        )
    )
    generation = instance.gate.generation
    assert instance.apply(command(instance, duration=0.05))["status"] == "accepted"
    instance.tick(0.02)
    clock.now += 0.06
    if dispatch_after_expiry:
        assert instance.apply(command(instance, duration=0.05))["status"] == "accepted"
    else:
        instance.tick(0.02)
        assert instance.controller.deadline == 0
        assert instance.controller.o_lx == instance.controller.o_az == 0
        assert instance.apply(command(instance, duration=0.05))["status"] == "accepted"
    assert ("stop",) in instance.adapter.calls
    assert instance.gate.state == "ARMED"
    assert instance.gate.generation == generation
    instance.tick(0.02)
    assert instance.controller.o_lx > 0
    instance.apply({"action": "stop"})
    assert instance.gate.state == "DISARMED"


def test_operator_pulse_stop_failure_disarms(executor):
    instance, clock = executor
    instance.apply(
        command(
            instance,
            "arm",
            owner="manual",
            operator_consent=True,
            operator_plan="Mock operator session",
            execution_context="panel",
            arming_mode="operator",
        )
    )
    instance.apply(command(instance, duration=0.05))
    instance.tick(0.02)
    instance.adapter.stop = lambda: False
    clock.now += 0.06
    instance.tick(0.02)
    assert instance.gate.state == "DISARMED"
    assert instance.gate.reason == "actuator_failed"


def test_http_operator_arm_envelope_reaches_executor_without_injected_lease(executor, monkeypatch):
    from services import safety_contract

    instance, clock = executor
    monkeypatch.setattr(safety_contract.time, "time", lambda: clock.now)
    payload = command(
        instance,
        "arm",
        owner="manual",
        operator_consent=True,
        operator_plan="Mock HTTP operator session",
        execution_context="panel",
        arming_mode="operator",
    )
    normalized = safety_contract.command_envelope(payload)
    assert "lease_s" not in normalized
    assert instance.apply(normalized)["status"] == "executed"
    assert instance.gate.arming_mode == "operator"
