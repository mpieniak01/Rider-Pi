"""Isolated motion ACK and transport failure regressions; no physical SDK."""

from __future__ import annotations

import pytest
from motion_fakes import FakeAdapter, FakeSDK, arm, command, executor as executor

from apps.motion.executor import MotionExecutor
from apps.safety.gate import MotionGate
from drivers.xgo.adapter import XgoAdapter


def test_superseded_goal_gets_terminal_ack_before_replacement(executor):
    instance, _ = executor
    arm(instance)
    first = command(instance, request_id="first", vx=0.2)
    assert instance.apply(first)["status"] == "accepted"
    second = command(instance, request_id="second", vx=-0.2)
    assert instance.apply(second)["status"] == "accepted"
    old_ack = next(ack for ack in instance.recent_acks if ack["request_id"] == "first")
    assert old_ack["status"] == "rejected" and old_ack["reason"] == "goal_superseded"
    assert old_ack["superseded_by"] == "second"
    assert instance.last_ack["request_id"] == "second"
    instance.tick(0.02)
    assert instance.last_ack["request_id"] == "second" and instance.last_ack["status"] == "executed"
    assert instance.adapter.calls[-1][0] == "move"
    assert instance.adapter.calls[-1][1] < 0


@pytest.mark.parametrize("action", ["stop", "disarm", "estop"])
def test_stop_actions_keep_cancelled_pending_terminal_ack(executor, action):
    instance, _ = executor
    arm(instance)
    instance.apply(command(instance, request_id="pending-goal"))
    stop_ack = instance.apply({"action": action, "request_id": "stop-request"})
    cancelled = next(ack for ack in instance.recent_acks if ack["request_id"] == "pending-goal")
    assert cancelled["status"] == "rejected" and cancelled["reason"] == f"cancelled_by_{action}"
    assert cancelled["cancelled_by"] == "stop-request"
    assert instance.pending is None
    assert instance.last_ack == stop_ack
    assert instance.last_ack["request_id"] == "stop-request"
    assert instance.last_ack["status"] == "executed"


@pytest.mark.parametrize("ttl", [501, 1000])
def test_direct_bus_ttl_uses_same_half_second_limit(executor, ttl):
    instance, _ = executor
    arm(instance)
    before = list(instance.adapter.calls)
    ack = instance.apply(command(instance, ttl_ms=ttl))
    assert ack["status"] == "rejected" and ack["reason"] == "expired_command"
    instance.tick(0.02)
    assert instance.adapter.calls == before


@pytest.mark.parametrize("failure", ["false", "raise"])
def test_unconfirmed_stop_latches_not_ready_and_cannot_rearm(executor, monkeypatch, failure):
    instance, _ = executor
    arm(instance)
    instance.apply(command(instance, request_id="pending-on-fault"))

    def failed_stop():
        instance.adapter.calls.append(("failed-stop",))
        if failure == "raise":
            raise OSError("isolated_uart_failure")
        return False

    monkeypatch.setattr(instance.adapter, "stop", failed_stop)
    ack = instance.apply({"action": "stop", "request_id": "unconfirmed-stop"})
    assert ack["status"] == "rejected" and ack["hardware_stop_sent"] is False
    assert ack["reason"] == "hardware_stop_unconfirmed"
    assert instance.snapshot()["ready"] is False
    assert instance.snapshot()["hardware_ready"] is False
    assert instance.snapshot()["can_move"] is False
    assert instance.snapshot()["read_only"] is True
    assert instance.snapshot()["error"].startswith("hardware_stop_")
    assert instance.gate.state == "DISARMED"
    assert instance.pending is None
    assert any(a["request_id"] == "pending-on-fault" and a["status"] == "rejected" for a in instance.recent_acks)

    # A transient fake transport recovery can retry STOP, but cannot revive this
    # executor's readiness or old operator consent.
    monkeypatch.setattr(instance.adapter, "stop", lambda: True)
    assert instance.apply({"action": "stop"})["hardware_stop_sent"] is True
    assert arm(instance)["reason"] == "hardware_unavailable"
    assert instance.snapshot()["ready"] is False
    assert not any(capability["available"] for capability in instance.capabilities().values())
    before = list(instance.adapter.calls)
    assert instance.apply(command(instance))["status"] == "rejected"
    assert instance.adapter.calls == before


def test_startup_stop_failure_requires_new_healthy_executor(executor):
    instance, clock = executor

    class UnconfirmedAdapter(FakeAdapter):
        def stop(self):
            self.calls.append(("failed-stop",))
            return False

    gate = MotionGate(clock=clock, wall_clock=clock, blocked=lambda: False)
    unhealthy = MotionExecutor(gate=gate, adapter=UnconfirmedAdapter(), status_writer=lambda _state: None)
    assert unhealthy.snapshot()["ready"] is False
    assert unhealthy.snapshot()["error"] == "hardware_stop_unconfirmed"
    assert arm(unhealthy)["status"] == "rejected"

    replacement_gate = MotionGate(clock=clock, wall_clock=clock, blocked=lambda: False)
    replacement = MotionExecutor(gate=replacement_gate, adapter=FakeAdapter(), status_writer=lambda _state: None)
    replacement.poll_sensors()  # Hardware readiness alone cannot grant permission.
    assert replacement.snapshot()["ready"] is True
    assert replacement.gate.state == "DISARMED"
    assert replacement.gate.generation != unhealthy.gate.generation
    assert arm(replacement)["status"] == "executed"


def test_failed_deadline_stop_blocks_future_arm(executor, monkeypatch):
    instance, clock = executor
    arm(instance)
    instance.apply(command(instance, duration=0.1))
    instance.tick(0.02)
    monkeypatch.setattr(instance.adapter, "stop", lambda: False)
    clock.now += 0.2
    instance.tick(0.02)
    assert instance.gate.state == "DISARMED"
    assert instance.snapshot()["ready"] is False
    assert instance.snapshot()["error"] == "hardware_stop_unconfirmed"
    assert arm(instance)["reason"] == "hardware_unavailable"


@pytest.mark.parametrize("failure", ["latched-error", "raised-error"])
def test_move_transport_failure_revokes_readiness(executor, monkeypatch, failure):
    instance, _ = executor
    arm(instance)

    def failed_move(**kwargs):
        if failure == "raised-error":
            raise OSError("isolated_uart_failure")
        instance.adapter.error = "sdk_call_failed:move:OSError"
        return False

    monkeypatch.setattr(instance.adapter, "move", failed_move)
    instance.apply(command(instance))
    instance.tick(0.02)
    assert instance.last_ack["status"] == "rejected"
    assert instance.gate.state == "DISARMED"
    assert instance.snapshot()["ready"] is False
    assert instance.snapshot()["error"]
    instance.adapter.error = None
    monkeypatch.setattr(instance.adapter, "move", lambda **kwargs: True)
    assert arm(instance)["reason"] == "hardware_unavailable"


@pytest.mark.parametrize("method", ["stop", "rider_move_x", "rider_read_battery"])
def test_sdk_transport_error_is_latched_but_stop_remains_retryable(executor, monkeypatch, tmp_path, method):
    instance, _ = executor
    physical = XgoAdapter(
        gate=instance.gate,
        owner=True,
        sdk_factory=FakeSDK,
        lock_path=tmp_path / "fault.lock",
        uart_probe=lambda _port: {"known": True, "owners": []},
    )
    assert physical.ok()
    try:
        arm(instance)
        original = getattr(physical._dog, method)

        def fail(*args, **kwargs):
            raise OSError("isolated_sdk_uart_failure")

        monkeypatch.setattr(physical._dog, method, fail)
        if method == "stop":
            assert physical.stop() is False
        elif method == "rider_move_x":
            assert physical.drive("forward", 0.1) is False
        else:
            assert physical.battery() is None
        assert physical.ok() is False
        assert "OSError" in physical.error
        assert physical.capabilities()["move"]["available"] is False
        assert physical.drive("forward", 0.1) is False
        monkeypatch.setattr(physical._dog, method, original)
        assert physical.stop() is True
        assert physical.ok() is False  # new owner required; no implicit recovery
    finally:
        physical.close()
