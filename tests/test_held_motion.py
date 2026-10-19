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
    assert instance.controller.stopped
    assert instance.controller.deadline == 0
    assert instance.gate.state == "ARMED"
    assert instance.gate.generation == generation


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


def test_manual_brake_cancels_pulse_and_preserves_operator_arm(executor):
    instance, clock = executor
    operator_arm(instance)
    generation = instance.gate.generation
    assert instance.apply(intent(instance, "pulse"))["status"] == "accepted"
    advance(instance, clock, 0.1)
    assert instance.apply(intent(instance, "release"))["status"] == "accepted"
    advance(instance, clock, 0.2)
    assert instance.controller.stopped
    assert instance.gate.state == "ARMED"
    assert instance.gate.generation == generation


def navigation_arm(instance):
    return instance.apply(
        command(
            instance,
            "arm",
            source="navigation",
            owner="navigation",
            execution_context="panel",
            operator_consent=True,
            operator_plan="Isolated navigation test",
            lease_s=10.0,
        )
    )


def navigation_pulse(instance, clock):
    return command(
        instance,
        source="navigation",
        execution_context="panel",
        duration=0.15,
        decision_deadline_monotonic=clock.now + 0.2,
    )


def test_navigation_pulse_end_stops_output_but_fresh_go_renews(executor):
    instance, clock = executor
    assert navigation_arm(instance)["status"] == "executed"
    generation = instance.gate.generation
    for _ in range(5):
        assert instance.apply(navigation_pulse(instance, clock))["status"] == "accepted"
        advance(instance, clock, 0.16)
        assert instance.controller.stopped
        assert instance.gate.state == "ARMED"
        assert instance.gate.generation == generation
    advance(instance, clock, 0.06)
    assert instance.gate.state == "DISARMED"
    assert instance.gate.reason == "decision_timeout"
    assert instance.controller.stopped


@pytest.mark.parametrize("tick_before_reply", [False, True])
def test_navigation_expired_go_cannot_restart_after_pulse(executor, tick_before_reply):
    instance, clock = executor
    navigation_arm(instance)
    assert instance.apply(navigation_pulse(instance, clock))["status"] == "accepted"
    advance(instance, clock, 0.16)
    late = navigation_pulse(instance, clock)
    clock.now += 0.06
    late.update(ts=clock.now, decision_deadline_monotonic=clock.now + 0.2)
    if tick_before_reply:
        instance.tick(0.02)
    assert instance.apply(late)["status"] == "rejected"
    assert instance.gate.state == "DISARMED"
    assert instance.controller.stopped


def test_navigation_stop_between_pulses_revokes_fresh_permit(executor):
    instance, clock = executor
    navigation_arm(instance)
    assert instance.apply(navigation_pulse(instance, clock))["status"] == "accepted"
    advance(instance, clock, 0.16)
    queued = navigation_pulse(instance, clock)
    instance.apply({"action": "stop", "source": "navigation"})
    assert instance.controller.remote_decision_deadline is None
    assert instance.apply(queued)["status"] == "rejected"
    assert instance.controller.stopped


def test_remote_decision_lease_and_real_executor_complete_multiple_pulses(executor):
    from apps.compute.decision_lease import DecisionLease
    from services.navigation_config import DEFAULT

    instance, clock = executor
    navigation_arm(instance)
    generation = instance.gate.generation
    policy = {**DEFAULT, "mode": "drive", "verified": True, "model_sha256": "a" * 64}
    acknowledgements = []

    def drive(speed, duration):
        payload = navigation_pulse(instance, clock)
        payload.update(vx=speed, duration=duration, decision_deadline_monotonic=lease.deadline)
        ack = instance.apply(payload)
        acknowledgements.append(ack)
        assert ack["status"] == "accepted"

    lease = DecisionLease(
        policy,
        "integration-run",
        drive,
        lambda: instance.apply({"action": "stop", "source": "navigation"}),
        clock,
    )
    for seq in range(1, 9):
        reply = {
            "protocol_version": 1,
            "run_id": "integration-run",
            "frame_id": f"f{seq}",
            "sequence": seq,
            "config_revision": policy["revision"],
            "action": "go",
            "state": "clear",
            "clear_count": 3,
            "valid_for_ms": 200,
            "model_sha256": policy["model_sha256"],
        }
        assert lease.accept(reply, f"f{seq}", seq, clock.now)
        advance(instance, clock, 0.16)
        assert lease.tick()
        assert instance.controller.stopped
        assert instance.gate.generation == generation
    assert len(acknowledgements) == 8
    reply.update(sequence=9, frame_id="f9", action="stop", state="obstacle", reason="obstacle")
    assert not lease.accept(reply, "f9", 9, clock.now)
    assert lease.latched
    assert instance.controller.stopped
    assert instance.gate.state == "DISARMED"
