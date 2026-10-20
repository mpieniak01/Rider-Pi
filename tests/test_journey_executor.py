"""Continuous navigation through the real executor with memory-only motors."""

import pytest
from journey_fakes import arm, goal, lease_for, reply
from motion_fakes import command, executor as executor
from test_held_motion import advance


def test_journey_remains_armed_for_ninety_seconds_only_with_fresh_feedback(executor):
    instance, clock = executor
    assert arm(instance)["status"] == "executed"
    generation = instance.gate.generation
    lease, acknowledgements = lease_for(instance, clock)
    started = clock()
    for index in range(900):
        row = reply(lease, index + 1)
        assert lease.accept(row, row["frame_id"], index + 1, clock() - 0.02)
        advance(instance, clock, 0.1)
        assert lease.tick()
        assert instance.gate.generation == generation
        assert instance.gate.state == "ARMED"
        assert 0 <= instance.controller.o_lx <= 0.1
        assert instance.gate.lease_deadline - clock() <= 0.3
    assert clock() - started == pytest.approx(90)
    assert len(acknowledgements) == 900
    assert lease.journey.context["maneuver_epoch"] == 0  # Clear travel never resets a maneuver budget.
    lease.halt("operator_stop")
    assert instance.gate.state == "DISARMED"
    assert instance.controller.stopped
    assert lease.journey.snapshot()["active"] is False


def test_feedback_loss_stops_after_original_permit_and_never_revives(executor):
    instance, clock = executor
    arm(instance)
    lease, _ = lease_for(instance, clock)
    row = reply(lease, 1, valid_for_ms=80)
    assert lease.accept(row, "f1", 1, clock())
    advance(instance, clock, 0.1)
    assert instance.controller.stopped
    assert instance.gate.state == "ARMED"
    assert lease.tick()
    row = reply(lease, 2)
    assert lease.accept(row, "f2", 2, clock() - 0.02)
    advance(instance, clock, 0.32)
    assert not lease.tick()
    assert instance.gate.state == "DISARMED"
    assert instance.gate.journey.snapshot()["reason"] == "decision_timeout"
    assert not lease.accept(reply(lease, 3), "f3", 3, clock())
    assert instance.controller.o_lx == instance.controller.o_az == 0


def test_get_snapshots_and_duplicate_arm_do_not_renew_bootstrap(executor):
    instance, clock = executor
    body = command(
        instance,
        "arm",
        source="manual",
        owner="navigation",
        arming_mode="journey",
        journey_version=1,
        journey_id="mission",
        execution_context="panel",
        panel_id="operator",
        operator_control_version=1,
        operator_consent=True,
        operator_plan="Isolated journey",
        request_id="journey-arm",
    )
    assert instance.apply(body)["status"] == "executed"
    deadline = instance.gate.lease_deadline
    for _ in range(4):
        advance(instance, clock, 1)
        instance.snapshot()
        assert instance.apply(body)["status"] == "rejected"
        assert instance.gate.lease_deadline == deadline
    advance(instance, clock, 1.02)
    assert instance.gate.state == "DISARMED"
    assert not instance.gate.journey.active
    assert instance.controller.stopped


@pytest.mark.parametrize(
    "invalid",
    [
        {"decision_deadline_monotonic": None},
        {"decision_feedback_deadline_monotonic": None},
        {"decision_feedback_deadline_monotonic": float("inf")},
        {"journey_id": "other"},
        {"journey_version": True},
        {"operator_operation_id": "obsolete"},
    ],
)
def test_bad_goals_never_renew_journey(executor, invalid):
    instance, clock = executor
    arm(instance)
    assert instance.apply(goal(instance, clock))["status"] == "accepted"
    deadline = instance.gate.lease_deadline
    advance(instance, clock, 0.02)
    assert instance.apply(goal(instance, clock, **invalid))["status"] == "rejected"
    assert instance.gate.lease_deadline <= deadline
    advance(instance, clock, 0.32)
    assert instance.gate.state == "DISARMED"
    assert instance.controller.stopped


def test_fresh_zero_goal_renews_only_short_feedback_budget(executor):
    instance, clock = executor
    arm(instance)
    for _ in range(150):
        result = instance.apply(goal(instance, clock, vx=0, yaw=0))
        assert result["status"] == "executed"
        assert instance.gate.lease_deadline <= clock() + 0.3
        advance(instance, clock, 0.1)
        assert instance.gate.state == "ARMED"
        assert instance.controller.stopped
    advance(instance, clock, 0.32)
    assert instance.gate.state == "DISARMED"


@pytest.mark.parametrize("action", ["stop", "disarm", "estop"])
def test_terminal_stop_rejects_inflight_old_goal_and_preserves_outcome(executor, action):
    instance, clock = executor
    arm(instance)
    assert instance.apply(goal(instance, clock))["status"] == "accepted"
    old = goal(instance, clock)
    assert instance.apply({"action": action})["status"] == "executed"
    finished = instance.gate.journey.snapshot()
    assert finished["id"] == "mission"
    assert finished["active"] is False
    assert instance.apply(old)["status"] == "rejected"
    advance(instance, clock, 0.1)
    assert instance.gate.journey.snapshot() == finished
    assert instance.controller.stopped


def test_manual_pause_ends_journey_and_cannot_resume_it(executor):
    instance, clock = executor
    arm(instance)
    instance.apply(goal(instance, clock))
    row = command(instance, "navigation_pause", panel_id="operator", execution_context="panel")
    assert instance.apply(row)["status"] == "executed"
    assert instance.gate.state == "DISARMED"
    assert instance.gate.journey.snapshot()["reason"] == "operator_intervention"
    resume = command(instance, "navigation_resume", panel_id="operator", execution_context="panel")
    assert instance.apply(resume)["status"] == "rejected"
    assert instance.controller.stopped


def test_manual_intervention_requires_new_explicit_manual_arm(executor):
    instance, clock = executor
    arm(instance)
    instance.apply(goal(instance, clock))
    row = command(instance, panel_id="operator", execution_context="panel", intervene=True)
    assert instance.apply(row)["reason"] == "navigation_journey_manual_arm_required"
    assert instance.gate.state == "DISARMED"
    assert instance.gate.journey.snapshot()["reason"] == "operator_intervention"
    assert instance.controller.stopped


def test_fresh_explicit_arm_starts_new_journey_but_cannot_swap_active_id(executor):
    instance, _ = executor
    arm(instance)
    assert arm(instance, journey_id="other", request_id="other-arm")["status"] == "rejected"
    assert instance.gate.journey.id == "mission"
    instance.apply({"action": "stop"})
    assert arm(instance, journey_id="other", request_id="other-arm-2")["status"] == "executed"
    assert instance.gate.journey.snapshot()["active"] is True
    assert instance.gate.journey.id == "other"


def test_feedback_expiring_during_controller_submission_returns_rejected_and_zero(executor, monkeypatch):
    instance, clock = executor
    arm(instance)
    original = instance.controller.drive

    def delayed(*args, **kwargs):
        result = original(*args, **kwargs)
        clock.now += 0.31
        return result

    monkeypatch.setattr(instance.controller, "drive", delayed)
    result = instance.apply(goal(instance, clock))
    assert result["status"] == "rejected"
    assert result["reason"] == "decision_feedback_deadline_expired"
    assert instance.gate.state == "DISARMED"
    assert not instance.gate.journey.active
    assert instance.controller.stopped


def test_controller_rejection_finishes_journey_immediately(executor, monkeypatch):
    instance, clock = executor
    arm(instance)
    monkeypatch.setattr(instance.controller, "drive", lambda *_args, **_kwargs: False)
    assert instance.apply(goal(instance, clock))["status"] == "rejected"
    assert instance.gate.state == "DISARMED"
    assert not instance.gate.journey.active
    assert instance.controller.stopped


@pytest.mark.parametrize("stop_confirmed", [True, False])
def test_unversioned_journey_intervention_finishes_previous_goal_and_reports_real_stop(
    executor, monkeypatch, stop_confirmed
):
    instance, clock = executor
    arm(instance)
    previous = goal(instance, clock, request_id="pending-navigation-goal")
    assert instance.apply(previous)["status"] == "accepted"
    real_stop = instance.controller.stop

    def stop():
        real_stop()
        return stop_confirmed

    monkeypatch.setattr(instance.controller, "stop", stop)
    row = command(instance, panel_id="operator", execution_context="panel", intervene=True, request_id="old-client")
    result = instance.apply(row)
    assert result["status"] == "rejected"
    assert result["hardware_stop_sent"] is stop_confirmed
    assert result["reason"] == (
        "navigation_journey_manual_arm_required" if stop_confirmed else "hardware_stop_unconfirmed"
    )
    previous_ack = next(ack for ack in instance.recent_acks if ack["request_id"] == previous["request_id"])
    assert previous_ack["status"] == "rejected"
    assert previous_ack["cancelled_by"] == row["request_id"]
    assert instance.pending is None
    assert instance.gate.state == "DISARMED"
