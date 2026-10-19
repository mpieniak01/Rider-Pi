from __future__ import annotations

import time

import pytest
from test_task_lifecycle import World

from services.core.features import FeatureManager, NullPublisher


def setup(tmp_path):
    world = World()
    manager = FeatureManager(
        runner=world.run,
        status_fn=world.status,
        publisher=NullPublisher(),
        safety_status=lambda: world.safety,
        safety_stop=world.stop,
        dependency_check=lambda *args: [],
        state_path=tmp_path / "state.json",
    )
    manager.producer_status = lambda unit: {
        "unit": unit,
        "accepted": True,
        "active": True,
        "observed_at": time.time(),
        "generation": world.safety.get("generation"),
        "request_id": manager._service_intents().get(unit, {}).get("request_id"),
    }
    intent = {
        "request_id": "operator-click",
        "generation": "operator-generation",
        "seq": 1,
        "source": "manual",
        "ts": time.time(),
        "ttl_ms": 500,
    }
    return world, manager, intent


@pytest.mark.parametrize(
    "change",
    [{"generation": "old"}, {"ts": 0}, {"seq": True}, {"ttl_ms": 501}, {"source": "unknown"}, {"request_id": ""}],
)
def test_stale_or_missing_intent_cannot_start_moving_task(tmp_path, change):
    world, manager, intent = setup(tmp_path)
    result = manager.set_feature("face_tracking", True, control={**intent, **change})
    assert result["error"] == "stale_or_invalid_operator_intent"
    assert world.actions == []


def test_missing_envelope_refused_even_with_matching_owner(tmp_path):
    world, manager, _ = setup(tmp_path)
    assert manager.set_feature("face_tracking", True)["error"] == "stale_or_invalid_operator_intent"
    assert world.actions == []


def test_replay_cannot_be_used_after_stop(tmp_path):
    world, manager, intent = setup(tmp_path)
    assert manager.set_feature("face_tracking", True, control=intent)["ok"]
    manager.set_feature("face_tracking", False)
    world.safety.update(ready=True, can_move=True, owner="follow_me", generation="operator-generation")
    assert manager.set_feature("face_tracking", True, control=intent)["error"] == "operator_intent_replay"


def test_rearm_during_start_cannot_change_original_generation(tmp_path):
    world, manager, intent = setup(tmp_path)
    original = world.run

    def changed_generation(unit, action):
        if unit == "rider-tracker.service" and action == "start":
            world.safety["generation"] = "new-operator-plan"
        return original(unit, action)

    manager.runner = changed_generation
    result = manager.set_feature("face_tracking", True, control=intent)
    assert result["error"] == "operator_generation_changed"
    assert not result["ok"]
    assert "rider-tracking-controller.service" not in world.active


def test_pending_task_carries_request_id_and_accepted_generation(tmp_path):
    world, manager, intent = setup(tmp_path)
    observed = []
    original = world.run

    def inspect_pending(unit, action):
        row = next(row for row in manager.describe_features() if row["name"] == "s3_follow_me_face")
        observed.append((row["request_id"], row["control_generation"]))
        return original(unit, action)

    manager.runner = inspect_pending
    result = manager.set_feature("face_tracking", True, control=intent)
    assert result["ok"]
    assert result["request_id"] == "operator-click"
    assert set(observed) == {("operator-click", "operator-generation")}


def test_generation_change_is_detected_before_controller_start(tmp_path):
    world, manager, intent = setup(tmp_path)
    original = world.run

    def rearm(unit, action):
        if unit == "rider-tracker.service" and action == "start":
            world.safety["generation"] = "different-plan"
        return original(unit, action)

    manager.runner = rearm
    assert manager.set_feature("face_tracking", True, control=intent)["error"] == "operator_generation_changed"
    assert ("rider-tracking-controller.service", "start") not in world.actions


def test_moving_task_requires_written_journal(tmp_path):
    world, manager, intent = setup(tmp_path)
    manager._state_path = tmp_path  # directory cannot be replaced by a file
    assert manager.set_feature("face_tracking", True, control=intent)["error"] == "control_journal_unavailable"
    assert world.actions == []


def test_unit_intent_is_published_before_controller_start(tmp_path):
    import json

    world, manager, intent = setup(tmp_path)
    original = world.run

    def read_journal(unit, action):
        if unit == "rider-tracking-controller.service" and action == "start":
            data = json.loads(manager._state_path.read_text())
            row = data["service_intents"][unit]
            assert row["generation"] == "operator-generation"
            assert row["request_id"] == "operator-click"
            assert row["task"] == "s3_follow_me_face"
        return original(unit, action)

    manager.runner = read_journal
    assert manager.set_feature("face_tracking", True, control=intent)["ok"]


def test_same_owner_rearm_does_not_make_old_task_ready(tmp_path):
    world, manager, intent = setup(tmp_path)
    assert manager.set_feature("face_tracking", True, control=intent)["ok"]
    world.safety["generation"] = "different-plan"
    task = next(row for row in manager.describe_features() if row["name"] == "s3_follow_me_face")
    assert task["ready"] is False
    assert task["state"] == "partial"


def test_administration_requires_written_journal(tmp_path):
    world, manager, intent = setup(tmp_path)
    manager._state_path = tmp_path
    assert (
        manager.service_action("rider-tracking-controller.service", "start", control=intent)["error"]
        == "control_journal_unavailable"
    )
    assert world.actions == []


def test_failed_admin_start_does_not_keep_replayable_intent(tmp_path):
    world, manager, intent = setup(tmp_path)
    world.fail.add(("rider-tracking-controller.service", "start"))
    result = manager.service_action("rider-tracking-controller.service", "start", control=intent)
    assert not result["ok"]
    assert manager.state_snapshot()["service_intents"] == {}


def test_admin_start_rearm_rolls_back_after_confirmed_stop(tmp_path):
    world, manager, intent = setup(tmp_path)
    original = world.run

    def rearm(unit, action):
        if action == "start":
            world.safety["generation"] = "different-plan"
        return original(unit, action)

    manager.runner = rearm
    result = manager.service_action("rider-tracking-controller.service", "start", control=intent)
    assert result["error"] == "operator_generation_changed"
    assert world.actions[-2:] == [("control", "stop"), ("rider-tracking-controller.service", "stop")]
