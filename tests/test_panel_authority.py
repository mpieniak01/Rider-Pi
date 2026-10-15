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


@pytest.mark.parametrize("invalid", ["", " " * 3, "x" * 129, 7, True])
def test_invalid_panel_identity_never_creates_authority(executor, invalid):
    instance, _ = executor
    assert arm_panel(instance, invalid)["reason"] == "invalid_panel_id"
    assert instance.gate.state == "DISARMED"
