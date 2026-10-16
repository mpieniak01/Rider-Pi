"""Exclusive manual panel ownership with in-memory SDK outputs only."""

import pytest
from motion_fakes import command, executor as executor


def arm_panel(instance, panel_id):
    return instance.apply(
        command(
            instance,
            "arm",
            owner="manual",
            arming_mode="operator",
            execution_context="panel",
            operator_consent=True,
            operator_plan="Isolated panel authority test",
            panel_id=panel_id,
        )
    )


def move_panel(instance, panel_id, mode="hold"):
    row = command(
        instance, panel_id=panel_id, execution_context="panel", device_settings=True, direction="forward", mode=mode
    )
    for key in ("vx", "yaw", "duration"):
        row.pop(key, None)
    return row


def test_manual_arm_binds_panel_and_reports_capability(executor):
    instance, _ = executor
    assert arm_panel(instance, "panel-a")["status"] == "executed"
    assert instance.snapshot()["panel_control"] == {"version": 1, "holder": "panel-a"}


@pytest.mark.parametrize("foreign", ["panel-b", None])
def test_other_panel_or_legacy_renewal_cannot_replace_or_brake_holder(executor, foreign):
    instance, _ = executor
    arm_panel(instance, "panel-a")
    assert instance.apply(move_panel(instance, "panel-a"))["status"] == "accepted"
    deadline = instance.controller.deadline
    before = list(instance.adapter.calls)
    row = move_panel(instance, foreign)
    if foreign is None:
        row.pop("panel_id")
    assert instance.apply(row)["reason"] == "panel_owner_mismatch"
    assert instance.controller.deadline == deadline
    assert instance.controller.t_lx > 0
    assert instance.adapter.calls == before


def test_repeated_arm_cannot_silently_take_another_panel(executor):
    instance, _ = executor
    arm_panel(instance, "panel-a")
    assert arm_panel(instance, "panel-b")["reason"] == "panel_owner_mismatch"
    assert instance.gate.panel_id == "panel-a"


def test_explicit_stop_and_arm_handover_invalidates_old_browser(executor):
    instance, _ = executor
    arm_panel(instance, "panel-a")
    old = move_panel(instance, "panel-a")
    instance.apply(old)
    old_generation = instance.gate.generation
    assert instance.apply({"action": "disarm"})["status"] == "executed"
    assert instance.gate.panel_id is None
    assert arm_panel(instance, "panel-b")["status"] == "executed"
    assert instance.gate.generation != old_generation
    assert instance.apply(old)["reason"] == "stale_generation"
    assert instance.apply(move_panel(instance, "panel-a"))["reason"] == "panel_owner_mismatch"
    assert instance.apply(move_panel(instance, "panel-b"))["status"] == "accepted"


def test_global_stop_from_other_panel_needs_no_motion_envelope(executor):
    instance, _ = executor
    arm_panel(instance, "panel-a")
    instance.apply(move_panel(instance, "panel-a"))
    assert instance.apply({"action": "stop", "panel_id": "panel-b"})["status"] == "executed"
    assert instance.gate.state == "DISARMED"
    assert instance.controller.stopped
    assert instance.gate.panel_id is None


@pytest.mark.parametrize("invalid", ["", " " * 3, "x" * 129, "x" + " " * 128, 7, True])
def test_invalid_panel_identity_never_creates_authority(executor, invalid):
    instance, _ = executor
    assert arm_panel(instance, invalid)["reason"] == "invalid_panel_id"
    assert instance.gate.state == "DISARMED"


def test_panel_renews_for_30_seconds_and_loss_of_renewals_stops_outputs(executor):
    from test_held_motion import advance

    instance, clock = executor
    arm_panel(instance, "panel-a")
    for _ in range(200):
        assert instance.apply(move_panel(instance, "panel-a"))["status"] == "accepted"
        advance(instance, clock, 0.16)
        assert instance.controller.o_lx > 0
    last = clock.now
    while not instance.controller.stopped and clock.now - last < 1:
        advance(instance, clock, 0.02)
    assert clock.now - last <= 0.6
    assert instance.controller.t_lx == 0 and instance.controller.o_lx == 0
    assert instance.gate.state == "ARMED"
    advance(instance, clock, 1)
    assert instance.controller.stopped
    assert instance.apply(move_panel(instance, "panel-a", "release"))["status"] == "accepted"
    assert instance.gate.panel_id == "panel-a"


@pytest.mark.parametrize("invalid", ["", " ", "x" * 129, True])
def test_malformed_panel_identity_does_not_brake_current_holder(executor, invalid):
    instance, _ = executor
    arm_panel(instance, "panel-a")
    instance.apply(move_panel(instance, "panel-a"))
    deadline = instance.controller.deadline
    calls = list(instance.adapter.calls)
    assert instance.apply(move_panel(instance, invalid))["reason"] == "invalid_panel_id"
    assert instance.controller.deadline == deadline
    assert instance.adapter.calls == calls


@pytest.mark.parametrize("panel", ["panel-b", None])
def test_invalid_foreign_actuator_values_do_not_brake_holder(executor, panel):
    instance, _ = executor
    arm_panel(instance, "panel-a")
    instance.apply(move_panel(instance, "panel-a"))
    calls, deadline = list(instance.adapter.calls), instance.controller.deadline
    malformed = command(instance, panel_id=panel, vx="bad", execution_context="panel")
    if panel is None:
        malformed.pop("panel_id")
    assert instance.apply(malformed)["reason"] == "panel_owner_mismatch"
    assert instance.controller.deadline == deadline and instance.adapter.calls == calls
    malformed["panel_id"] = "panel-a"
    assert instance.apply(malformed)["status"] == "rejected"
    assert instance.controller.stopped


def test_timed_arm_does_not_accidentally_bind_a_panel(executor):
    from motion_fakes import arm

    instance, _ = executor
    assert arm(instance, panel_id="panel-a")["status"] == "executed"
    assert instance.gate.panel_id is None
    assert arm(instance, panel_id="panel-a")["status"] == "executed"


def test_legacy_operator_arm_requires_explicit_stop_before_binding(executor):
    instance, _ = executor
    from test_manual_settings import operator_arm

    assert operator_arm(instance)["status"] == "executed"
    assert arm_panel(instance, "panel-a")["reason"] == "panel_owner_mismatch"
    assert instance.gate.panel_id is None
