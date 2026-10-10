"""Check UI paths/methods without dispatching robot or service commands."""

from __future__ import annotations

import pytest

from services.api_core import version_api
from services.api_server import app


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/services/graph"),
        ("GET", "/api/status/version"),
        ("GET", "/api/logic/summary"),
        ("GET", "/api/providers/state"),
        ("GET", "/api/control/state"),
        ("GET", "/api/system/ai-mode"),
        ("GET", "/api/motion/queue"),
        ("GET", "/api/resource/camera"),
        ("POST", "/api/control"),
        ("POST", "/api/control/balance"),
        ("POST", "/api/control/height"),
        ("POST", "/api/logic/feature/face_tracking"),
        ("POST", "/vision/tracking/mode"),
        ("POST", "/api/vision/tracking/mode"),
        ("POST", "/api/navigator/return_home"),
        ("PATCH", "/api/providers/voice"),
        ("PUT", "/api/system/ai-mode"),
        ("GET", "/svc"),
        ("POST", "/svc/rider-api.service"),
        ("POST", "/api/resource/camera"),
        ("POST", "/api/chat/send"),
        ("POST", "/api/voice/tts"),
        ("POST", "/api/voice/providers/test"),
        ("GET", "/api/home/devices"),
        ("POST", "/api/home/auth"),
        ("POST", "/api/home/command"),
    ],
)
def test_operator_routes_match_supported_http_methods(method, path):
    endpoint, _ = app.url_map.bind("localhost").match(path, method=method)
    assert endpoint in app.view_functions


def test_invalid_feature_payload_is_400_not_missing_route():
    response = app.test_client().post("/api/logic/feature/face_tracking", json={})
    assert response.status_code == 400
    assert response.get_json()["error"] == "enabled_required"


def test_version_route_is_registered_in_full_application(monkeypatch):
    expected = {"available": True, "branch": "test", "commit": "a1b2c3d", "dirty": False}
    monkeypatch.setattr(version_api, "get_version_info", lambda: expected)
    response = app.test_client().get("/api/status/version")
    assert response.status_code == 200
    assert response.get_json() == expected


def test_wrong_method_and_unknown_route_are_distinct():
    client = app.test_client()
    assert client.get("/api/control").status_code == 405
    assert client.get("/api/does-not-exist").status_code == 404


@pytest.mark.parametrize("prefix", ["", "/api"])
def test_vision_aliases_keep_options_and_deprecated_response(prefix):
    client = app.test_client()
    assert client.options(prefix + "/vision/cam").status_code == 200
    assert client.post(prefix + "/vision/follow/face", json={}).status_code == 410
    assert client.post(prefix + "/vision/follow/hand", json={}).status_code == 410
