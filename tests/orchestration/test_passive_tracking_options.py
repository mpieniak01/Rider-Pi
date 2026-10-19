"""Passive tracking choices use the same task journal and fake BUS only."""

import json

from flask import Flask
from test_task_lifecycle import World

from common.service_catalog import DEFAULT_REGISTRY, option_schema
from services.api_core import features_api, vision_api


def test_passive_hand_has_no_motion_owner_intent_or_controller(tmp_path):
    world = World()
    world.safety = {"ready": False, "can_move": False, "owner": None}
    manager = world.manager(tmp_path)
    result = manager.set_feature("s6_tracker_module", True, options={"mode": "hand"})
    assert result["ok"]
    assert result["task"]["tracking_mode"] == "hand"
    assert "rider-tracking-controller.service" not in world.active
    assert manager.publisher.sent == [("tracking.mode:set", {"mode": "hand"})]
    assert manager._service_intents() == {}
    journal = json.loads((tmp_path / "state.json").read_text())
    assert journal["service_intents"] == {}
    assert result["task"]["can_move"] is False
    assert option_schema(DEFAULT_REGISTRY["s6_tracker_module"])["end_value"] == "none"


def test_conflicting_passive_mode_never_changes_requested_followme(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    assert manager.set_feature("face_tracking", True)["ok"]
    before_actions, before_messages = list(world.actions), list(manager.publisher.sent)
    before_intents = manager._service_intents()
    result = manager.set_feature("s6_tracker_module", True, options={"mode": "hand"})
    assert result["error"] == "resource_conflict"
    assert result["blocked_by"] == ["s3_follow_me_face"]
    assert world.actions == before_actions
    assert manager.publisher.sent == before_messages
    assert manager._service_intents() == before_intents


def test_none_ends_only_passive_consumer_and_keeps_shared_followme_mode(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    assert manager.set_feature("s6_tracker_module", True, options={"mode": "face"})["ok"]
    assert manager.set_feature("face_tracking", True)["ok"]
    world.actions.clear()
    result = manager.set_feature("s6_tracker_module", True, options={"mode": "none"})
    assert result["ok"]
    assert result["task"]["requested"] is False
    assert "s3_follow_me_face" in manager._requested
    assert "rider-tracker.service" in world.active
    assert "rider-tracking-controller.service" in world.active
    assert world.actions == [("rider-tracker.target", "stop")]
    assert manager.publisher.sent[-1] == ("tracking.mode:set", {"mode": "face"})


def test_failed_stop_of_followme_does_not_change_shared_mode(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    assert manager.set_feature("face_tracking", True)["ok"]
    world.stop_confirmed = False
    before = list(manager.publisher.sent)
    assert manager.set_feature("face_tracking", False)["error"] == "stop_unconfirmed"
    assert manager.set_feature("s6_tracker_module", True, options={"mode": "hand"})["error"] == "resource_conflict"
    assert manager.publisher.sent == before


def test_legacy_wrapper_uses_real_orchestrator_and_preserves_public_contract(tmp_path, monkeypatch):
    world = World()
    manager = world.manager(tmp_path)
    monkeypatch.setattr(features_api, "feature_manager", manager)
    monkeypatch.setattr(vision_api, "_tracking_pub", lambda: (_ for _ in ()).throw(AssertionError("Direct BUS bypass")))
    app = Flask(__name__)
    app.register_blueprint(vision_api.bp)
    client = app.test_client()
    assert client.get("/vision/tracking/mode").get_json()["mode"] == "none"
    assert world.actions == []
    assert manager.publisher.sent == []
    response = client.post("/vision/tracking/mode", json={"mode": "HAND", "enabled": True})
    assert response.status_code == 200
    assert response.get_json()["mode"] == "hand"
    assert response.get_json()["enabled"] is True
    assert manager.publisher.sent[-1] == ("tracking.mode:set", {"mode": "hand"})
    assert client.post("/vision/tracking/mode", json={"mode": "hand", "enabled": False}).get_json()["mode"] == "none"
    assert manager.publisher.sent[-1] == ("tracking.mode:set", {"mode": "none"})
    assert client.post("/vision/tracking/mode", json={"mode": [], "enabled": True}).status_code == 400
    assert client.post("/vision/tracking/mode", json={"mode": "face", "enabled": "false"}).status_code == 400


def test_legacy_wrapper_reports_conflict_without_publish(tmp_path, monkeypatch):
    world = World()
    manager = world.manager(tmp_path)
    assert manager.set_feature("face_tracking", True)["ok"]
    monkeypatch.setattr(features_api, "feature_manager", manager)
    before = list(manager.publisher.sent)
    app = Flask(__name__)
    app.register_blueprint(vision_api.bp)
    response = app.test_client().post("/vision/tracking/mode", json={"mode": "hand"})
    assert response.status_code == 409
    assert response.get_json()["blocked_by"] == ["s3_follow_me_face"]
    assert manager.publisher.sent == before
