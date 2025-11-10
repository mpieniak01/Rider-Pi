from __future__ import annotations

import json
from typing import Any, Iterator

import pytest

from services import api_server
from services.api_core import voice_local_proxy


class DummyResp:
    def __init__(self, body: bytes, status: int = 200, headers: dict[str, str] | None = None):
        self._body = body
        self.status = status
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> DummyResp:
        return self

    def __exit__(self, *exc) -> None:
        return None


@pytest.fixture()
def client() -> Iterator[Any]:
    with api_server.app.test_client() as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def reset_provider_status(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    voice_local_proxy._PROVIDER_STATUS.clear()

    def fake_service_status(alias: str | None):
        if not alias:
            return None
        return {"unit": alias, "active": "inactive", "alias": alias}

    monkeypatch.setattr(voice_local_proxy, "_service_status", fake_service_status)
    yield
    voice_local_proxy._PROVIDER_STATUS.clear()


def test_voice_provider_list_initial_state(client: Any) -> None:
    resp = client.get("/api/voice/providers")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert len(data["providers"]) >= 1
    assert data["providers"][0]["status"]["state"] == "unknown"
    assert data["providers"][0]["service"] == "voice-web"
    assert data["providers"][0]["service_state"]["unit"] == "voice-web"


def test_voice_provider_test_success(monkeypatch: pytest.MonkeyPatch, client: Any) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(req: Any, timeout: float):
        captured["payload"] = json.loads((req.data or b"{}").decode("utf-8"))
        body = json.dumps({"status": "ok", "audio_b64": "QUJD"}).encode("utf-8")
        return DummyResp(body, headers={"Content-Type": "application/json"})

    monkeypatch.setattr(voice_local_proxy.urllib.request, "urlopen", fake_urlopen)

    resp = client.post("/api/voice/providers/test", json={"provider": "local"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["results"][0]["state"] == "ok"
    assert captured["payload"]["backend"] in ("local", "piper")

    resp2 = client.get("/api/voice/providers")
    assert resp2.status_code == 200
    status = resp2.get_json()["providers"][0]["status"]["state"]
    assert status in ("ok", "error")


def test_tts_proxy_preserves_backend(monkeypatch: pytest.MonkeyPatch, client: Any) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(req: Any, timeout: float):
        captured["payload"] = json.loads((req.data or b"{}").decode("utf-8"))
        body = json.dumps({"status": "ok", "audio_b64": "QUJD"}).encode("utf-8")
        return DummyResp(body, headers={"Content-Type": "application/json"})

    monkeypatch.setattr(voice_local_proxy.urllib.request, "urlopen", fake_urlopen)

    resp = client.post("/api/voice/tts", json={"text": "hej", "backend": "openai", "voice": "ash"})
    assert resp.status_code == 200
    assert captured["payload"]["backend"] == "openai"


def test_google_voice_normalized(monkeypatch: pytest.MonkeyPatch, client: Any) -> None:
    monkeypatch.setattr(
        voice_local_proxy,
        "_PROVIDER_DEFS",
        [
            {
                "id": "google",
                "label": "Google Gemini",
                "backend": "google",
                "voice": "pl_PL-gosia-medium",
                "model": None,
                "description": "",
                "service": None,
            }
        ],
        raising=False,
    )
    resp = client.get("/api/voice/providers")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["providers"][0]["voice"] == "Kore"
