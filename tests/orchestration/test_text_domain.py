"""Text-only profile readiness and routing never load ASR/TTS or open I/O."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from test_domains_and_readiness import healthy
from test_task_lifecycle import World

from apps.voice import domain_profiles, domain_worker
from common.service_catalog import DEFAULT_REGISTRY, task_resources, task_units
from services.api_core import chat_glue, text_profile


def test_text_has_only_http_worker_and_no_audio_resources():
    units = task_units(DEFAULT_REGISTRY["s10_ai_providers"], {"domain": "text"})
    assert "rider-voice-web.service" in units and "rider-voice.service" not in units
    assert not {"mic", "speaker"} & set(task_resources(DEFAULT_REGISTRY["s10_ai_providers"], {"domain": "text"}))
    assert domain_profiles.expand("text") == {"chat"}


def test_missing_backend_heartbeat_cannot_make_text_task_ready(tmp_path):
    manager = World().manager(tmp_path)
    manager.producer_status = lambda _: {"stale": True, "ready": False, "missing": ["chat_backend_disabled"]}
    result = manager.set_feature("s10_ai_providers", True, options={"domain": "text"})
    assert result["ok"] and result["task"]["state"] == "starting" and not result["task"]["ready"]
    assert result["task"]["producer_statuses"]


def test_default_text_backend_is_explicitly_unavailable(monkeypatch):
    monkeypatch.setenv("VOICE_WEB_LLM_PROVIDER", "stub")
    status = domain_profiles.availability({"chat"}, find_spec=lambda _: pytest.fail("text imported audio backend"))
    assert status["ready"] is False and status["missing"] == ["chat_backend_disabled"]


def test_chat_only_worker_imports_no_audio_model(monkeypatch):
    legacy = SimpleNamespace(_local_vosk_model=object(), _local_piper_voice=object())
    monkeypatch.setattr(domain_worker, "availability", healthy)
    monkeypatch.setattr(domain_worker, "worker_bind", lambda: ("127.0.0.1", 8092))
    monkeypatch.setattr(domain_worker, "write_status", lambda _: None)
    status = domain_worker.update_profile(legacy, {"chat"})
    assert status["ready"] and status["chat_endpoint"] == "http://127.0.0.1:8092/api/chat"
    assert legacy._local_vosk_model is None and legacy._local_piper_voice is None


def test_text_routing_requires_fresh_matching_worker(monkeypatch):
    monkeypatch.setattr(text_profile, "requested_domains", lambda: {"chat"})
    status = {
        "stale": False,
        "pid": 42,
        "domains": ["chat"],
        "capabilities": {"chat": {"ready": True}},
        "chat_endpoint": "http://127.0.0.1:8092/api/chat",
    }
    monkeypatch.setattr(text_profile.task_runtime, "read_status", lambda _: status)
    monkeypatch.setattr(text_profile.systemd_ctrl, "status", lambda _: {"pid": 42, "active": "active"})
    assert text_profile.selected_endpoint() == status["chat_endpoint"]
    status["pid"] = 43
    assert text_profile.selected_endpoint() is None
    status["pid"], status["stale"] = 42, True
    assert text_profile.selected_endpoint() is None
    status["stale"] = False
    status["capabilities"]["chat"]["ready"] = False
    assert text_profile.selected_endpoint() is None


def test_selected_text_glue_sends_real_chat_payload_without_echo(monkeypatch):
    import urllib.request

    monkeypatch.delenv("CHAT_REMOTE_URL", raising=False)
    monkeypatch.setattr(text_profile, "selected_endpoint", lambda: "http://127.0.0.1:8092/api/chat")
    calls = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, *args):
            return b'{"ok":true,"text":"model reply"}'

    def fake_open(request, **kwargs):
        calls.append((request.full_url, json.loads(request.data)))
        return FakeResponse()

    monkeypatch.setattr(chat_glue, "_open_selected_worker", fake_open)
    assert chat_glue._try_remote_api("operator prompt") == (True, "model reply")
    assert calls == [
        (
            "http://127.0.0.1:8092/api/chat",
            {"text": "operator prompt", "messages": [{"role": "user", "content": "operator prompt"}]},
        )
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"ok": False, "error": "backend unavailable"},
        {"ok": True, "source": "echo", "text": "prompt"},
        {"ok": True, "source": "mock", "text": "demo"},
        {"ok": True, "demo": True, "text": "demo"},
        {"ok": True, "error": "partial failure", "text": "unused"},
        {"ok": True, "model": "configured", "usage": {}},
        {"ok": True, "reply": {"status": "active"}},
    ],
)
def test_http_200_error_echo_or_metadata_never_becomes_ai_success(monkeypatch, payload):
    import urllib.request

    monkeypatch.setenv("CHAT_REMOTE_URL", "http://configured.test/api/chat")

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, *args):
            return json.dumps(payload).encode()

    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())
    assert chat_glue._try_remote_api("operator prompt")[0] is False


@pytest.mark.parametrize("ok,source,expected_status", [(True, "pc", 200), (False, "unavailable", 503)])
def test_chat_http_preserves_provenance_and_marks_echo_failure(monkeypatch, ok, source, expected_status):
    from flask import Flask

    app = Flask(__name__)
    chat_glue.register(app)
    monkeypatch.setattr(chat_glue, "_remote_reply", lambda _: (ok, "reply or error", source))
    monkeypatch.setattr(chat_glue, "_store_add", lambda item: item)
    response = app.test_client().post("/api/chat/send", json={"text": "prompt"})
    assert response.status_code == expected_status
    assert response.get_json()["ok"] is ok
    assert response.get_json()["source"] == (source if ok else "echo")
