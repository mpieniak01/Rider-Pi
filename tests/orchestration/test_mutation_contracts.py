"""Actual registered wrappers with injected domain results, without effects."""

import pytest

from services import api_server
from services.api_core import chat_glue, face_anim, face_api, home_auth_route, voice_proxy

VENDOR = {"Accept": "application/vnd.rider.api+json;version=1"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api_server, "face_render_shim", lambda row: {"ok": True, "out": "fixture.png"})
    monkeypatch.setattr(face_api, "draw_face", lambda row: ({"ok": True, "out": "fixture.png"}, 200))
    monkeypatch.setattr(face_anim, "play", lambda row: {"ok": True, "state": {"playing": True}})
    monkeypatch.setattr(face_anim, "stop", lambda row: {"ok": True, "state": {"playing": False}})
    monkeypatch.setattr(chat_glue, "_store_add", lambda row: row)
    monkeypatch.setattr(chat_glue, "_try_local_agent", lambda text: (False, ""))
    monkeypatch.setattr(chat_glue, "_remote_reply", lambda text: (True, "real fixture response", "fixture-backend"))
    monkeypatch.setattr(voice_proxy, "_forward", lambda *args: ({"ok": True, "text": "fixture"}, 200))
    monkeypatch.setattr(home_auth_route, "build_auth_url_preview", lambda: {"ok": False})
    monkeypatch.setattr(api_server.google_home_api, "start_oauth_flow", lambda: {"ok": True, "message": "saved"})
    monkeypatch.setattr(api_server.google_home_api, "is_authenticated", lambda: True)
    monkeypatch.setattr(api_server.google_home_api, "send_command", lambda *args: {"ok": True, "result": {}})
    monkeypatch.setattr(api_server, "_save_command_cache", lambda *args: None)
    return api_server.app.test_client()


@pytest.mark.parametrize("path", ["/face/render", "/api/draw/face", "/draw/face", "/face/play", "/face/stop"])
def test_face_application_results_keep_alias_evidence(client, path):
    response = client.post(path, json={}, headers=VENDOR)
    body = response.get_json()
    assert response.status_code == 200 and body["ok"]
    assert body["operation"]["ack_kind"] == "application_result"
    assert body["operation"]["confirmed"] is True and body["operation"]["actuation"] is False


@pytest.mark.parametrize("path", ["/api/chat", "/api/chat/send"])
def test_actual_chat_alias_response_is_an_application_result(client, path):
    response = client.post(path, json={"text": "fixture"}, headers=VENDOR)
    body = response.get_json()
    assert response.status_code == 200 and body["ok"]
    assert body["data"]["reply"] == "real fixture response"
    assert body["operation"]["ack_kind"] == "application_result"


@pytest.mark.parametrize("path,payload", [("/api/voice/say", {"text": "fixture"}), ("/api/voice/capture?sec=1", {})])
def test_voice_backend_result_is_preserved(client, path, payload):
    response = client.post(path, json=payload, headers=VENDOR)
    assert response.status_code == 200 and response.get_json()["operation"]["confirmed"] is True


@pytest.mark.parametrize(
    "path,payload", [("/api/home/auth", {}), ("/api/home/command", {"deviceId": "fixture", "command": "fixture"})]
)
def test_home_domain_result_is_preserved(client, path, payload):
    response = client.post(path, json=payload, headers=VENDOR)
    assert response.status_code == 200 and response.get_json()["operation"]["ack_kind"] == "application_result"


def test_chat_backend_failure_is_not_an_application_success(client, monkeypatch):
    monkeypatch.setattr(chat_glue, "_remote_reply", lambda text: (False, "fixture_backend_unavailable", "unavailable"))
    response = client.post("/api/chat", json={"text": "fixture"}, headers=VENDOR)
    assert response.status_code == 503 and response.get_json()["ok"] is False
    assert response.get_json()["operation"]["confirmed"] is False
    assert response.get_json()["operation"]["status"] == "rejected"
