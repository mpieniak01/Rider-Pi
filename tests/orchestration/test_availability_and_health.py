"""Fake executor/systemd facts only; passive baseline is not movement permission."""

from types import SimpleNamespace

import pytest
from test_task_lifecycle import World

from common.service_action_guard import check
from common.service_catalog import DEFAULT_REGISTRY, task_availability, unit_availability
from services.api_core.bus_health import snapshot


@pytest.mark.parametrize("task", ["s4_recon", "s9_navigation"])
def test_unavailable_task_denied_before_intent_persistence_or_effect(tmp_path, task):
    world = World()
    manager = world.manager(tmp_path)
    result = manager.set_feature(task, True)
    assert result["error"] == "navigation_traversal_unverified"
    assert not world.actions and not manager._intents and not manager._pending
    assert task not in manager._requested
    assert task_availability(DEFAULT_REGISTRY[task])["start_available"] is False


def test_direct_navigator_admin_and_privileged_guard_use_same_availability(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    assert not unit_availability("rider-navigator.service")["start_available"]
    assert check("rider-navigator.service", "start")["error"] == "navigation_traversal_unverified"
    assert manager.service_action("rider-navigator.service", "start")["error"] == "navigation_traversal_unverified"
    assert not world.actions


def test_starting_base_executor_does_not_require_arm_or_write_moving_intent(tmp_path):
    world = World()
    world.active.discard("motion-executor.service")
    world.safety.update(ready=False, can_move=False, owner=None, state="ESTOP")
    manager = world.manager(tmp_path)
    assert manager.service_action("motion-executor.service", "start")["ok"]
    assert manager._admin_intents == {}
    assert check("motion-executor.service", "start")["ok"]
    assert world.actions == [("motion-executor.service", "start")]


@pytest.mark.parametrize("available,at", [(False, 999), (True, None), (True, 900), (True, float("inf")), (True, 1005)])
def test_bus_no_data_or_bad_time_is_not_ready(available, at):
    namespace = SimpleNamespace(_ZMQ_OK=available, LAST_MSG_TS=at, LAST_HEARTBEAT_TS=None)
    result = snapshot(namespace, now=1000, safety={"observed_at": 1000, "instance_id": "fixture"})
    assert not result["ready"] and not result["bus"]["connected"]
    assert result["api"]["live"] and result["observed_at"] is None


def test_executor_live_does_not_mean_physical_motion_ready():
    namespace = SimpleNamespace(_ZMQ_OK=True, LAST_MSG_TS=999, LAST_HEARTBEAT_TS=999)
    result = snapshot(
        namespace,
        now=1000,
        safety={"observed_at": 1000, "instance_id": "fixture", "ready": False, "can_move": False, "state": "ESTOP"},
    )
    assert result["ready"] and result["components"]["executor"]["live"]
    assert result["bus"]["transport"]["received_at"] == 999
    assert result["bus"]["observed_at"] is None
