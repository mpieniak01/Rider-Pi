from __future__ import annotations

import pytest
from flask import Flask
from test_task_lifecycle import World

from services.api_core import features_api, services_api


def app_and_world(monkeypatch, tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    monkeypatch.setattr(features_api, "feature_manager", manager)
    monkeypatch.setattr(services_api.systemd_ctrl, "status", world.status)
    app = Flask(__name__)
    app.add_url_rule("/api/logic/features", view_func=features_api.feature_registry_handler)
    app.add_url_rule("/api/logic/summary", view_func=features_api.feature_summary_handler)
    app.add_url_rule("/api/logic/catalog", view_func=features_api.feature_catalog_handler)
    app.add_url_rule("/api/logic/feature/<name>", view_func=features_api.feature_handler, methods=["POST"])
    app.add_url_rule("/svc", view_func=services_api.svc_list)
    app.add_url_rule("/svc/<name>", view_func=services_api.svc_action, methods=["POST"])
    return app.test_client(), world, manager


def test_read_only_contract_is_truthful_and_never_opens_bus(monkeypatch, tmp_path):
    client, world, manager = app_and_world(monkeypatch, tmp_path)
    for path in ["/api/logic/features", "/api/logic/summary", "/api/logic/catalog", "/svc"]:
        response = client.get(path)
        data = response.get_json()
        assert response.status_code == 200 and data["contract_version"] == 2
        assert data["host"] == "pi" and data["observed_at"]
    assert world.actions == [] and manager.publisher.sent == []


def test_invalid_bool_or_options_cannot_enable_task(monkeypatch, tmp_path):
    client, world, _ = app_and_world(monkeypatch, tmp_path)
    assert client.post("/api/logic/feature/s6_tracker_module", json={"enabled": "false"}).status_code == 400
    assert (
        client.post(
            "/api/logic/feature/s7_obstacle_module", json={"enabled": True, "options": {"provider": "typo"}}
        ).status_code
        == 400
    )
    assert world.actions == []


def test_expired_permission_returns_conflict_without_unit_action(monkeypatch, tmp_path):
    client, world, _ = app_and_world(monkeypatch, tmp_path)
    world.safety = {"ready": False, "can_move": False, "owner": None}
    assert client.post("/api/logic/feature/face_tracking", json={"enabled": True}).status_code == 409
    assert client.post("/svc/navigator", json={"action": "start"}).status_code == 409
    assert world.actions == []


def test_dependency_failure_never_becomes_http_success(monkeypatch, tmp_path):
    client, world, _ = app_and_world(monkeypatch, tmp_path)
    world.fail.add(("rider-tracker.service", "start"))
    response = client.post("/api/logic/feature/s6_tracker_module", json={"enabled": True})
    assert response.status_code == 503 and response.get_json()["ok"] is False


def test_operator_stop_cannot_steal_camera_and_optional_enable_denied(monkeypatch, tmp_path):
    client, world, manager = app_and_world(monkeypatch, tmp_path)
    assert manager.set_feature("s6_tracker_module", True)["ok"]
    assert client.post("/svc/camera", json={"action": "stop"}).status_code == 409
    assert client.post("/svc/jupyter", json={"action": "enable"}).status_code == 409


@pytest.mark.parametrize("payload", [[1], "start", 1, None])
def test_nonobject_payload_never_mutates_tasks_or_services(monkeypatch, tmp_path, payload):
    client, world, _ = app_and_world(monkeypatch, tmp_path)
    for path in ["/svc/camera", "/api/logic/feature/s6_tracker_module"]:
        assert client.post(path, json=payload).status_code == 400
    assert world.actions == []


def test_application_registers_catalog_v2(monkeypatch, tmp_path):
    from services import api_server

    _, world, manager = app_and_world(monkeypatch, tmp_path)
    client = api_server.app.test_client()
    response = client.get("/api/logic/catalog")
    assert response.status_code == 200
    assert response.get_json()["contract_version"] == 2
    assert response.get_json()["units"]
    assert client.options("/api/logic/catalog").status_code == 204
    assert world.actions == [] and manager.publisher.sent == []
