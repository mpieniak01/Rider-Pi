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


@pytest.mark.parametrize(
    "action,fields",
    [
        ("move", {}),
        ("turn", {"yaw": 0.1}),
        ("balance", {"enabled": True}),
        ("height", {"height": 4}),
        ("action", {"name": "wave"}),
    ],
)
def test_all_actuators_rejected_disarmed(executor, action, fields):
    instance, _ = executor
    before = list(instance.adapter.calls)
    ack = instance.apply(command(instance, action, **fields))
    assert ack["status"] == "rejected"
    assert ack["reason"] == "motion_disarmed"
    assert instance.adapter.calls == before


def test_permission_requires_consent_and_plan(executor):
    instance, _ = executor
    assert instance.apply(command(instance, "arm"))["reason"] == "operator_consent_required"
    assert instance.apply(command(instance, "arm", operator_consent=True))["reason"] == "operator_plan_required"
    assert arm(instance)["status"] == "executed"
    assert instance.snapshot()["state"] == "ARMED"
    assert not any(call[0] == "move" for call in instance.adapter.calls)


def test_stop_invalidates_old_generation_and_clears_target(executor):
    instance, _ = executor
    arm(instance)
    previous = command(instance)
    assert instance.apply(previous)["status"] == "accepted"
    instance.tick(0.02)
    assert instance.last_ack["status"] == "executed"
    stop = instance.apply({"action": "stop"})
    assert stop["hardware_stop_sent"] is True
    assert instance.snapshot()["moving"] is False
    assert instance.controller.t_lx == instance.controller.o_lx == 0
    before = list(instance.adapter.calls)
    assert instance.apply(previous)["reason"] == "stale_generation"
    instance.tick(0.02)
    assert instance.adapter.calls == before


@pytest.mark.parametrize(
    "fields,reason",
    [
        ({"ts": 900.0}, "expired_command"),
        ({"ts": 1002.0}, "expired_command"),
        ({"ttl_ms": 3000}, "expired_command"),
        ({"generation": "old"}, "stale_generation"),
        ({"seq": -1}, "stale_sequence"),
        ({"source": "navigation"}, "owner_mismatch"),
        ({"vx": float("nan")}, "invalid_vx"),
        ({"duration": 1.0}, "motion_limits_exceeded"),
    ],
)
def test_invalid_or_delayed_goals_never_execute(executor, fields, reason):
    instance, _ = executor
    arm(instance)
    before = list(instance.adapter.calls)
    assert instance.apply(command(instance, **fields))["reason"] == reason
    instance.tick(0.02)
    assert instance.adapter.calls == before


def test_estop_is_latched_and_clear_does_not_rearm(executor):
    instance, _ = executor
    arm(instance)
    instance.apply(command(instance))
    instance.tick(0.02)
    instance.apply({"action": "estop"})
    assert estop.ESTOP_FLAG.exists()
    assert instance.gate.state == "ESTOP"
    assert instance.apply(command(instance))["reason"] == "estop_latched"
    assert (
        instance.apply(
            command(
                instance,
                "clear_estop",
                operator_consent=True,
                operator_plan="Mock E-Stop reset",
            )
        )["status"]
        == "executed"
    )
    assert instance.gate.state == "DISARMED"
    assert not estop.ESTOP_FLAG.exists()


def test_lease_timeout_stops_and_restart_does_not_restore_consent(executor):
    instance, clock = executor
    arm(instance)
    instance.apply(command(instance))
    instance.tick(0.02)
    clock.now += 11.0
    instance.tick(0.02)
    assert instance.gate.state == "DISARMED"
    assert instance.controller.stopped
    replacement = MotionGate(clock=clock, wall_clock=clock, blocked=lambda: False)
    assert replacement.state == "DISARMED"
    assert replacement.generation != instance.gate.generation


def test_duration_stops_without_new_goal_and_ack_is_stable(executor):
    instance, clock = executor
    arm(instance)
    instance.apply(command(instance, duration=0.1))
    instance.tick(0.02)
    ack = dict(instance.last_ack)
    clock.now += 0.2
    instance.tick(0.02)
    assert instance.controller.stopped
    assert instance.last_ack == ack


def test_passive_tracking_and_bare_legacy_commands_do_not_drive(executor):
    instance, _ = executor
    arm(instance)
    before = list(instance.adapter.calls)
    assert instance.apply({"target": {"x": 1.0}}, topic="tracking.pose")["status"] == "rejected"
    assert instance.apply({"vx": 0.5, "duration": 0.2}, topic="cmd.move")["status"] == "rejected"
    instance.tick(0.02)
    assert instance.adapter.calls == before


def test_exit_stops_then_closes_hardware(executor):
    instance, _ = executor
    arm(instance)
    instance.apply(command(instance))
    instance.tick(0.02)
    instance.close()
    assert instance.adapter.calls[-2:] == [("stop",), ("close",)]
    assert instance.gate.state == "DISARMED"
    assert instance.snapshot()["ready"] is False


def test_stop_wins_burst_and_self_telemetry_cannot_form_feedback(executor):
    instance, _ = executor
    arm(instance)
    move = command(instance)
    before = list(instance.adapter.calls)
    instance.process_batch(
        [
            ("motion.command", move),
            ("cmd.stop", {"request_id": "stop-request"}),
            ("motion.command", move),
            ("motion.state", {"action": "arm"}),
            ("motion.ack", {"action": "move"}),
        ]
    )
    instance.tick(0.02)
    assert instance.adapter.calls == before + [("stop",)]
    assert instance.last_ack["request_id"] == "stop-request"
    assert instance.last_ack["accepted"] is True
    assert instance.gate.state == "DISARMED"


def test_state_reads_fail_closed_and_do_not_import_sdk(monkeypatch, tmp_path):
    path = tmp_path / "status.json"
    monkeypatch.setenv("MOTION_STATE_PATH", str(path))
    assert read_status()["state"] == "UNKNOWN"
    write_status(
        {
            "contract_version": 1,
            "state": "ARMED",
            "observed_at": time.time() - 10,
            "ready": True,
            "hardware_ready": True,
            "can_move": True,
        }
    )
    assert read_status()["error"] == "executor_stale"
    assert read_status()["can_move"] is False
    path.write_text(json.dumps({"contract_version": 2}))
    assert read_status()["state"] == "UNKNOWN"


def test_adapter_default_is_inert_and_owner_init_cannot_reset(monkeypatch, tmp_path, executor):
    instance, _ = executor
    before = len(FakeSDK.constructed)
    adapter = XgoAdapter(sdk_factory=FakeSDK, lock_path=tmp_path / "owner.lock")
    assert not adapter.ok()
    assert len(FakeSDK.constructed) == before

    def free(_port):
        return {"known": True, "owners": []}

    physical = XgoAdapter(
        gate=instance.gate,
        owner=True,
        sdk_factory=FakeSDK,
        lock_path=tmp_path / "owner.lock",
        uart_probe=free,
    )
    try:
        assert physical.ok()
        assert ("reset",) not in physical._dog.events
        assert ("write", "ACTION") not in physical._dog.events
        assert ("write", "IMU") not in physical._dog.events
        assert physical.battery() == 0.8
        assert physical.imu() == {"roll": 1.0, "pitch": 2.0, "yaw": 3.0}
        assert physical.drive("forward", 0.2) is False
        second = XgoAdapter(
            gate=instance.gate,
            owner=True,
            sdk_factory=FakeSDK,
            lock_path=tmp_path / "owner.lock",
            uart_probe=free,
        )
        assert not second.ok()
        assert "BlockingIOError" in second.error
        arm(instance)
        assert physical.drive("forward", 0.2) is True
        instance.gate.disarm()
        assert physical.drive("forward", 0.2) is False
        assert physical.enable_balance(True) is False
        assert physical.set_height(90) is False
        assert physical.action("wave") is False
        assert physical.stop() is True
    finally:
        physical.close()


@pytest.mark.parametrize("execution_context", ["panel", "test"])
def test_physical_factory_refused_during_isolated_tests(monkeypatch, executor, tmp_path, execution_context):
    instance, _ = executor
    assert arm(instance, execution_context=execution_context, test_operator_consent=True)["status"] == "executed"
    assert instance.snapshot()[execution_context + "_motion_enabled"] is True
    monkeypatch.setenv("RIDER_TEST_ISOLATED", "1")
    physical = XgoAdapter(gate=instance.gate, owner=True, lock_path=tmp_path / "unused.lock")
    assert physical.error == "physical_sdk_blocked_in_tests"
    assert not (tmp_path / "unused.lock").exists()


def test_sensor_projection_marks_old_or_missing_data_unknown():
    imu, device = project_sensor_payload({"ts": 50, "imu": {"yaw": 1}, "battery": 0.8}, now=100)
    assert imu["stale"] is True
    assert device["battery_pct"] is None
    imu, device = project_sensor_payload({"observed_at": 100, "imu": {"roll": 1, "pitch": 2, "yaw": 3}}, now=100)
    assert imu["imu_ok"] is True
    assert device["pose"] == {"x": 1, "y": 2, "z": 3}


@pytest.mark.parametrize(
    "invalid",
    [
        {"action": {}},
        {"source": []},
        {"source": {}},
        {"seq": True},
        {"seq": 2**70},
        {"action": "action", "action_id": {}},
    ],
)
def test_malformed_bus_objects_are_rejected_without_process_failure(executor, invalid):
    instance, _ = executor
    arm(instance)
    before = list(instance.adapter.calls)
    assert instance.apply(command(instance, **invalid))["status"] == "rejected"
    instance.tick(0.02)
    assert instance.adapter.calls == before


def test_env_and_legacy_enable_flag_never_arm(monkeypatch, executor, tmp_path):
    _, clock = executor
    flag = tmp_path / "motion.enable"
    flag.touch()
    monkeypatch.setattr(estop, "MOTION_ENABLE_FLAG", flag)
    monkeypatch.setenv("MOTION_ENABLE", "1")
    gate = MotionGate(clock=clock, wall_clock=clock)
    assert gate.state == "DISARMED"
    assert gate.can_actuate() is False


def test_single_bounded_sensor_transaction_while_disarmed(executor):
    instance, clock = executor
    transactions = []
    instance.adapter.read_sensor = lambda name: transactions.append(name) or 1.0
    for _ in range(6):
        before = len(transactions)
        instance.poll_sensors()
        assert len(transactions) == before + 1
        clock.now += 0.2
    assert instance.gate.state == "DISARMED"
    assert not any(call[0] == "move" for call in instance.adapter.calls)


def test_sdk_failure_reports_rejected_ack_and_disarms(executor):
    instance, _ = executor
    arm(instance)
    instance.adapter.move = lambda **_kwargs: False
    instance.apply(command(instance))
    instance.tick(0.02)
    assert instance.last_ack["status"] == "rejected"
    assert instance.last_ack["reason"] == "actuator_failed"
    assert instance.gate.state == "DISARMED"
    assert instance.snapshot()["moving"] is False


def test_existing_noncooperating_uart_owner_blocks_sdk_initialization(executor, tmp_path):
    instance, _ = executor
    proc = tmp_path / "proc"
    descriptors = proc / "144437" / "fd"
    descriptors.mkdir(parents=True)
    (descriptors / "9").symlink_to("/dev/ttyAMA0")
    inventory = uart_inventory("/dev/ttyAMA0", proc_root=proc)
    assert inventory == {"known": True, "owners": [144437], "unreadable": []}
    constructed = len(FakeSDK.constructed)
    physical = XgoAdapter(
        gate=instance.gate,
        owner=True,
        sdk_factory=FakeSDK,
        lock_path=tmp_path / "owner.lock",
        uart_probe=lambda _port: inventory,
    )
    assert not physical.ok()
    assert "uart_owned_by_existing_process" in physical.error
    assert len(FakeSDK.constructed) == constructed


def test_unknown_uart_inventory_fails_closed(executor, tmp_path):
    instance, _ = executor
    constructed = len(FakeSDK.constructed)
    physical = XgoAdapter(
        gate=instance.gate,
        owner=True,
        sdk_factory=FakeSDK,
        lock_path=tmp_path / "owner.lock",
        uart_probe=lambda _port: {"known": False, "owners": []},
    )
    assert not physical.ok()
    assert "uart_inventory_unreadable" in physical.error
    assert len(FakeSDK.constructed) == constructed


def test_ack_ledger_retains_only_terminal_states_and_is_bounded(executor):
    instance, _ = executor
    arm(instance)
    instance.apply(command(instance))
    assert not any(ack["status"] == "accepted" for ack in instance.recent_acks)
    instance.tick(0.02)
    assert instance.recent_acks[-1]["status"] == "executed"
    for index in range(25):
        instance.apply(command(instance, request_id=f"rejected-{index}", generation="old"))
    ledger = instance.snapshot()["recent_acks"]
    assert len(ledger) == 16
    assert ledger[-1]["request_id"] == "rejected-24"
    assert ledger[-1]["command_generation"] == "old"


@pytest.mark.parametrize("operation", ["mkdir", "touch"])
def test_estop_persistence_failure_never_prevents_stop(executor, monkeypatch, operation):
    instance, _ = executor
    arm(instance)
    instance.apply(command(instance, request_id="pending-before-estop"))
    instance.tick(0.02)
    before = len(instance.adapter.calls)
    with monkeypatch.context() as failures:
        failures.setattr(
            type(estop.ESTOP_FLAG),
            operation,
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("isolated_disk_failure")),
        )
        ack = instance.apply({"action": "estop", "request_id": "estop-request"})
        assert ack["status"] == "executed" and ack["hardware_stop_sent"] is True
        assert instance.gate.state == "ESTOP"
        assert instance.snapshot()["persistence_error"].startswith("estop_persistence_failed")
        assert instance.adapter.calls[before:] == [("stop",)]
        assert instance.gate.can_actuate() is False
    cleared = instance.apply(command(instance, "clear_estop", operator_consent=True, operator_plan="Isolated reset"))
    assert cleared["status"] == "executed"
    assert instance.gate.state == "DISARMED"
    assert instance.snapshot()["persistence_error"] is None


def test_existing_estop_latch_does_not_write_each_poll(executor, monkeypatch):
    instance, _ = executor
    instance.apply({"action": "estop"})
    assert estop.ESTOP_FLAG.exists()

    def forbidden_write(*args, **kwargs):
        raise AssertionError("An existing latch must not be rewritten by polling")

    monkeypatch.setattr(type(estop.ESTOP_FLAG), "touch", forbidden_write)
    for _ in range(5):
        assert instance.gate.can_actuate() is False


def test_explicit_sdk_stop_never_polls_gate(executor, monkeypatch, tmp_path):
    instance, _ = executor
    physical = XgoAdapter(
        gate=instance.gate,
        owner=True,
        sdk_factory=FakeSDK,
        lock_path=tmp_path / "stop.lock",
        uart_probe=lambda _port: {"known": True, "owners": []},
    )
    assert physical.ok()
    try:
        physical._dog.events.clear()

        def broken_gate():
            raise OSError("isolated_gate_failure")

        monkeypatch.setattr(instance.gate, "can_actuate", broken_gate)
        assert physical.stop() is True
        assert physical._dog.events == [("write", "VX"), ("write", "VYAW")]
    finally:
        physical.close()


def test_sdk_stop_rejects_posture_write_even_when_armed(executor, monkeypatch, tmp_path):
    instance, _ = executor
    arm(instance)
    physical = XgoAdapter(
        gate=instance.gate,
        owner=True,
        sdk_factory=FakeSDK,
        lock_path=tmp_path / "stop-allowlist.lock",
        uart_probe=lambda _port: {"known": True, "owners": []},
    )
    assert physical.ok()
    try:
        physical._dog.events.clear()
        monkeypatch.setattr(physical._dog, "stop", lambda: physical._dog._XGO__send("ACTION"))
        assert physical.stop() is False
        assert ("write", "ACTION") not in physical._dog.events
    finally:
        physical.close()


def test_native_rider_mapping_uses_bounded_speed_and_protocol_neutral(monkeypatch, tmp_path, executor):
    import sys

    from common.motion_mapping import LINEAR_LEVELS, MAPPING_ID, linear_sdk_value, native_command_byte

    instance, _ = executor
    orders = {"VX": [0x30, 0], "VY": [0x31, 0], "VYAW": [0x32, 0]}
    monkeypatch.setattr(sys.modules[__name__], "XGOorder", orders, raising=False)

    class RecordingSDK(FakeSDK):
        def rider_move_x(self, speed, runtime=0):
            self.events.append(("native_linear", speed, runtime))
            super().rider_move_x(speed, runtime)

        def _XGO__send(self, key, index=1, len=1):
            self.events.append(("byte", key, orders[key][1]))

    adapter = XgoAdapter(
        gate=instance.gate,
        owner=True,
        sdk_factory=RecordingSDK,
        lock_path=tmp_path / "mapping.lock",
        uart_probe=lambda _: {"known": True, "owners": []},
    )
    try:
        assert adapter.ok()
        assert ("byte", "VX", 128) in adapter._dog.events
        assert ("byte", "VYAW", 128) in adapter._dog.events
        arm(instance)
        for direction, sign in [("forward", 1), ("backward", -1)]:
            for speed in [0, 0.01, 0.1, 0.5, 1]:
                assert adapter.drive(direction, speed)
                level = sign * round(speed * LINEAR_LEVELS)
                native = linear_sdk_value(level)
                assert ("native_linear", native, 0) in adapter._dog.events
                assert abs(native) <= 1.5
                assert adapter.output_status()["linear_step"] == level
                assert adapter.output_status()["linear_sdk_value"] == native
                assert adapter._dog.events[-1] == ("byte", "VX", native_command_byte(native, 1.5))
        assert linear_sdk_value(round(0.1 * LINEAR_LEVELS)) < 0.2
        assert adapter.output_status()["mapping_id"] == MAPPING_ID
        assert adapter.drive("forward", 0.01)
        assert 128 < adapter._dog.events[-1][2] < 140
        instance.gate.disarm()
        assert adapter.stop()
        assert adapter._dog.events[-2:] == [("byte", "VX", 128), ("byte", "VYAW", 128)]
    finally:
        adapter.close()


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
