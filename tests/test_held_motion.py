"""Targeted continuous manual intent tests. Fake adapter only."""

import pytest
from motion_fakes import command, executor as executor
from test_manual_settings import operator_arm

from apps.motion import manual_settings as settings


def intent(instance, mode="hold", direction="forward", **kw):
    row = command(instance, device_settings=True, direction=direction, mode=mode, execution_context="panel", **kw)
    for key in ("vx", "yaw", "duration"):
        row.pop(key, None)
    return row


def advance(instance, clock, seconds):
    for _ in range(round(seconds / 0.02)):
        clock.now += 0.02
        instance.poll_sensors()
        instance.tick(0.02)


def test_renewal_keeps_output_without_pulse_braking(executor):
    instance, clock = executor
    row = settings.read()
    settings.update({}, row["revision"], directions={"forward": {"speed": 0.6}})
    operator_arm(instance)
    for _ in range(8):
        assert instance.apply(intent(instance))["status"] == "accepted"
        advance(instance, clock, 0.16)
    assert instance.controller.o_lx == pytest.approx(0.6)
    assert instance.gate.state == "ARMED"
    advance(instance, clock, 0.52)
    assert instance.controller.stopped
    assert instance.gate.state == "ARMED"


def test_release_decelerates_without_revoking_permission(executor):
    instance, clock = executor
    operator_arm(instance)
    instance.apply(intent(instance))
    advance(instance, clock, 0.12)
    before = instance.controller.o_lx
    generation = instance.gate.generation
    assert instance.apply(intent(instance, "release"))["status"] == "accepted"
    advance(instance, clock, 0.02)
    assert 0 <= instance.controller.o_lx < before
    advance(instance, clock, 0.1)
    assert instance.controller.stopped and instance.controller.deadline == 0
    assert instance.gate.state == "ARMED" and instance.gate.generation == generation


def test_reversal_replaces_goal_through_zero(executor):
    instance, clock = executor
    operator_arm(instance)
    instance.apply(intent(instance))
    advance(instance, clock, 0.1)
    instance.apply(intent(instance, direction="backward"))
    outputs = []
    for _ in range(12):
        advance(instance, clock, 0.02)
        outputs.append(instance.controller.o_lx)
    assert any(abs(v) < 1e-8 for v in outputs)
    assert outputs[-1] < 0


@pytest.mark.parametrize("context", ["test", "panel"])
def test_hold_cannot_bypass_context_or_timed_arming(executor, context):
    from motion_fakes import arm

    instance, _ = executor
    arm(instance)
    before = list(instance.adapter.calls)
    payload = intent(instance)
    payload["execution_context"] = context
    assert instance.apply(payload)["reason"] == "hold_operator_panel_only"
    assert instance.adapter.calls == before


def test_late_renewal_after_release_cannot_restart(executor):
    instance, clock = executor
    operator_arm(instance)
    instance.apply(intent(instance))
    old = intent(instance)
    release = intent(instance, "release")
    release["seq"] += 1
    instance.apply(release)
    assert instance.apply(old)["reason"] == "stale_sequence"
    assert instance.controller.stopped


def test_stop_wins_over_renewal_and_invalidates_generation(executor):
    instance, _ = executor
    operator_arm(instance)
    old = intent(instance)
    instance.process_batch([("motion.command", old), ("motion.command", {"action": "stop"})])
    assert instance.gate.state == "DISARMED"
    assert instance.controller.stopped
    assert instance.apply(old)["status"] == "rejected"


def test_device_describes_each_unit_and_independent_limits(executor):
    row = settings.snapshot()
    schema = row["parameter_schema"]["direction_fields"]
    assert schema["speed"]["display_factor"] == 100
    assert schema["duration"]["display_factor"] == 1000
    assert schema["maximum"]["maximum"] == 1
    assert row["directions"]["forward"]["maximum"] <= schema["maximum"]["maximum"]
    assert row["control_modes"]["hold_timeout_ms"] == 500


def test_obsolete_renewal_does_not_cancel_newer_direction(executor):
    instance, clock = executor
    operator_arm(instance)
    old = intent(instance)
    newer = intent(instance, direction="backward")
    newer["seq"] += 1
    assert instance.apply(newer)["status"] == "accepted"
    assert instance.apply(old)["reason"] == "stale_sequence"
    advance(instance, clock, 0.1)
    assert instance.controller.o_lx < 0
    assert instance.gate.state == "ARMED"
