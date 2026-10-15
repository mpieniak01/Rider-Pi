"""Vision trial through the real executor classes; SDK and clocks are in memory."""

import random
from dataclasses import replace

import pytest
from motion_fakes import executor as executor
from test_held_motion import advance, navigation_arm, navigation_pulse
from test_navigation_runner import isolated

from apps.compute.decision_lease import DecisionLease
from apps.compute.navigation import NavigationRunner
from services.navigation_config import DEFAULT


def trial(instance, clock):
    assert navigation_arm(instance)["status"] == "executed"
    instance.controller.limits = replace(
        instance.controller.limits, linear_rate=0.5, linear_deceleration=1.0, ramp_mode=0
    )
    config = {**DEFAULT, "mode": "drive", "verified": True, "model_sha256": "a" * 64}
    acknowledgements = []
    generation = instance.gate.generation

    def output(speed, duration):
        payload = navigation_pulse(instance, clock)
        payload.update(vx=speed, duration=duration, decision_deadline_monotonic=lease.deadline)
        ack = instance.apply(payload)
        acknowledgements.append(ack)
        if ack["status"] not in {"accepted", "executed"}:
            raise RuntimeError(ack["reason"])

    def stop():
        instance.apply({"action": "stop", "source": "navigation", "expected_generation": generation})

    lease = DecisionLease(config, "trial", output, stop, clock, pause=lambda duration: output(0.0, duration))
    return lease, config, acknowledgements, generation


def reply(config, seq, *, state="clear", count=3, reason=None):
    return {
        "protocol_version": 1,
        "run_id": "trial",
        "frame_id": f"camera-{seq}",
        "sequence": seq,
        "config_revision": config["revision"],
        "action": "go" if state == "clear" and count >= 3 else "stop",
        "state": state,
        "clear_count": count,
        "reason": reason or ("depth_plane_candidate" if state == "clear" else "depth_ground_deviation"),
        "valid_for_ms": 200,
        "model_sha256": config["model_sha256"],
    }


def accept(lease, config, clock, seq, **kwargs):
    row = reply(config, seq, **kwargs)
    return lease.accept(row, row["frame_id"], seq, clock.now - 0.04)


def test_visual_stop_and_fresh_clear_resume_without_rearming(executor):
    instance, clock = executor
    lease, config, acks, generation = trial(instance, clock)
    original_deadline = instance.gate.lease_deadline
    assert accept(lease, config, clock, 1)
    advance(instance, clock, 0.08)
    assert instance.controller.o_lx > 0
    assert not accept(lease, config, clock, 2, state="obstacle", count=0)
    assert instance.controller.o_lx == instance.controller.o_az == 0
    assert not lease.latched and not lease.moving
    for seq, count in [(3, 1), (4, 2), (5, 3)]:
        advance(instance, clock, 0.08)
        assert lease.tick()
        assert accept(lease, config, clock, seq, count=count) is (count == 3)
        assert instance.gate.generation == generation
        assert instance.gate.lease_deadline == original_deadline
    advance(instance, clock, 0.08)
    assert instance.controller.o_lx > 0
    lease.halt("operator_stop")
    assert instance.controller.stopped and instance.gate.state == "DISARMED"
    assert not accept(lease, config, clock, 6)
    assert any(row["reason"] == "sdk_zero_accepted" for row in acks)


@pytest.mark.parametrize("reason", ["vision_image_quality", "depth_ground_orientation"])
def test_uncertain_image_pauses_and_keeps_original_trial(executor, reason):
    instance, clock = executor
    lease, config, _, generation = trial(instance, clock)
    assert accept(lease, config, clock, 1)
    advance(instance, clock, 0.06)
    assert not accept(lease, config, clock, 2, state="unknown", count=0, reason=reason)
    assert instance.controller.o_lx == 0
    assert not lease.latched and instance.gate.generation == generation


def test_inference_failure_is_terminal_even_before_first_motion(executor):
    instance, clock = executor
    lease, config, _, _ = trial(instance, clock)
    assert not accept(lease, config, clock, 1, state="unknown", count=0, reason="vision_inference_unavailable")
    assert lease.latched and instance.gate.state == "DISARMED"
    assert not accept(lease, config, clock, 2)


def test_paused_link_loss_expires_without_fresh_go(executor):
    instance, clock = executor
    lease, config, _, _ = trial(instance, clock)
    assert not accept(lease, config, clock, 1, state="obstacle", count=0)
    advance(instance, clock, 0.22)
    assert not lease.tick()
    assert lease.latched and instance.gate.state == "DISARMED"
    assert instance.controller.o_lx == 0
    assert not accept(lease, config, clock, 2)


@pytest.mark.parametrize("seed", range(100))
def test_full_ten_seconds_clear_produces_small_motor_outputs_and_then_stops(executor, seed):
    instance, clock = executor
    lease, config, _, generation = trial(instance, clock)
    rng = random.Random(seed)
    starts = clock.now
    due = 0
    seq = 0
    for step in range(500):
        if step >= due:
            seq += 1
            frame = reply(config, seq)
            assert lease.accept(frame, frame["frame_id"], seq, clock.now - rng.uniform(0.01, 0.05))
            due = step + rng.randint(4, 6)
        advance(instance, clock, 0.02)
        assert lease.tick()
        assert not lease.latched and instance.gate.generation == generation
        assert 0 <= instance.controller.o_lx <= 0.1
    assert clock.now - starts == pytest.approx(10.0)
    assert any(call[0] == "move" and call[1] > 0 for call in instance.adapter.calls)
    advance(instance, clock, 0.04)
    assert instance.gate.state == "DISARMED" and instance.controller.stopped
    assert instance.controller.o_lx == 0


def test_zero_visual_goal_does_not_count_as_started_motion(isolated):
    runner = NavigationRunner()
    runner.lease.deadline = runner.clock() + 0.15
    runner.pause(0.15)
    assert isolated[-1][-1]["vx"] == 0
    assert not runner.motion_started
    runner.drive(0.1, 0.15)
    assert runner.motion_started
