"""Review regressions inject every backend, process and heartbeat operation."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from flask import g
from test_domains_and_readiness import healthy
from test_task_lifecycle import World

from apps.voice import config, domain_profiles, domain_worker
from common import runtime_dependencies
from common.service_catalog import DEFAULT_REGISTRY, task_units


@pytest.mark.parametrize("selected", [None, "", "voice_local_file.toml"])
def test_availability_and_real_chat_handler_use_identical_config(monkeypatch, tmp_path, selected):
    monkeypatch.setenv("VOICE_WEB_LOAD_PROFILE", "0")
    monkeypatch.setenv("VOICE_WEB_LLM_PROVIDER", "local")
    if selected is None:
        monkeypatch.delenv("VOICE_DOMAIN_CONFIG", raising=False)
    else:
        monkeypatch.setenv("VOICE_DOMAIN_CONFIG", selected)
    binary, model = tmp_path / "llama", tmp_path / "model.gguf"
    binary.write_text("not executed")
    binary.chmod(0o700)
    model.write_text("not loaded")
    monkeypatch.setenv("VOICE_LLM_MAIN_PATH", str(binary))
    monkeypatch.setenv("VOICE_LLM_MODEL_PATH", str(model))
    paths = []

    def load(path):
        paths.append(path)
        return {"chat": {"backend": "local" if path else "stub"}}

    monkeypatch.setattr(config, "load", load)
    status = domain_profiles.availability({"chat"}, find_spec=lambda _: pytest.fail("audio import"))
    from apps.voice import web

    with web.app.test_request_context():
        web._load_config()
        assert g.config.chat.backend == ("local" if selected else "stub")
    assert paths == [selected or None, selected or None]
    assert status["ready"] is bool(selected)


@pytest.mark.parametrize(
    "payload,configured",
    [
        ({"text": "fixture", "backend": "openai"}, "local"),
        ({"text": "fixture", "provider": "gemini"}, "local"),
        ({"text": "fixture", "tts": "openai"}, "local"),
        ({"text": "fixture"}, "openai"),
        ({"text": "fixture", "backend": "", "provider": "gemini"}, "local"),
        ({"text": "fixture", "backend": {"backend": "local"}}, "local"),
        ({"text": "fixture", "backend": True}, "local"),
        ({"text": "fixture"}, ""),
        ([{"text": "fixture"}], "local"),
        ("fixture", "local"),
        (None, "local"),
    ],
)
@pytest.mark.parametrize("content_type", ["application/json", "text/plain"])
def test_local_tts_guard_rejects_cloud_defaults_aliases_and_invalid_payload(
    monkeypatch, payload, configured, content_type
):
    monkeypatch.setenv("VOICE_WEB_LOAD_PROFILE", "0")
    from apps.voice import web

    monkeypatch.setattr(config, "load", lambda path: {"tts": {"backend": configured}})
    monkeypatch.setattr(web, "api_tts", lambda: pytest.fail("TTS guard admitted invalid request"))
    monkeypatch.setattr(domain_worker, "requested_domains", lambda: {"tts"})
    monkeypatch.setattr(domain_worker, "availability", healthy)
    client = domain_worker.create_app(web, profile_status=lambda: {"stale": False, **healthy({"tts"})}).test_client()
    response = client.post("/api/tts", data=json.dumps(payload), content_type=content_type)
    assert response.status_code == 400
    assert response.get_json()["error"] in {"invalid_tts_payload", "selected_profile_is_local_tts"}


@pytest.mark.parametrize("field", ["backend", "provider", "tts"])
def test_local_tts_guard_accepts_normalized_alias_without_rewriting_payload(monkeypatch, field):
    monkeypatch.setenv("VOICE_WEB_LOAD_PROFILE", "0")
    from apps.voice import web

    monkeypatch.setattr(config, "load", lambda path: {"tts": {"backend": "openai"}})
    payload = {"text": "fixture", field: " PiPeR "}
    monkeypatch.setattr(web, "api_tts", lambda: {"ok": True, "payload": web.request.get_json(force=True)})
    monkeypatch.setattr(domain_worker, "requested_domains", lambda: {"tts"})
    monkeypatch.setattr(domain_worker, "availability", healthy)
    client = domain_worker.create_app(web, profile_status=lambda: {"stale": False, **healthy({"tts"})}).test_client()
    response = client.post("/api/tts", data=json.dumps(payload), content_type="text/plain")
    assert response.status_code == 200 and response.get_json()["payload"] == payload


@pytest.mark.parametrize(
    "failure", [OSError("temporary write failure"), ValueError("temporary status"), RuntimeError()]
)
def test_heartbeat_recovers_after_one_failure_without_stopping_worker(monkeypatch, capsys, failure):
    calls = []

    class FakeStop:
        def wait(self, interval):
            assert interval == 0.5
            return len(calls) == 2

    def update(legacy, domains):
        calls.append(domains)
        if len(calls) == 1:
            raise failure
        return healthy(domains)

    monkeypatch.setattr(domain_worker, "requested_domains", lambda: {"tts"})
    monkeypatch.setattr(domain_worker, "update_profile", update)
    domain_worker.observe_profiles(SimpleNamespace(), FakeStop())
    assert calls == [{"tts"}, {"tts"}]
    assert "voice_profile_heartbeat_failed" in capsys.readouterr().err


def test_default_s10_preflight_and_readiness_require_only_chat(monkeypatch, tmp_path):
    probed = []
    monkeypatch.setattr(
        runtime_dependencies.importlib.util,
        "find_spec",
        lambda module: probed.append(module) or (None if module in {"piper", "vosk"} else object()),
    )
    manager = World().manager(tmp_path)
    manager.dependency_check = runtime_dependencies.missing
    manager.producer_status = lambda unit: {"stale": False, **healthy({"chat"})}
    result = manager.set_feature("s10_ai_providers", True)
    assert result["ok"] and result["task"]["ready"]
    assert not {"piper", "vosk"} & set(probed)
    assert result["task"]["producer_statuses"][0]["domains"] == ["chat"]
    probed.clear()
    result = manager.set_feature("s5_voice", True)
    assert result["error"] == "runtime_dependencies_missing"
    assert set(result["missing"]) == {"piper", "vosk"}


def test_worker_dependency_fallback_distinguishes_text_and_full_voice(monkeypatch):
    probed = []
    monkeypatch.setattr(
        runtime_dependencies.importlib.util, "find_spec", lambda module: probed.append(module) or object()
    )
    runtime_dependencies.missing(task_units(DEFAULT_REGISTRY["s10_ai_providers"]), {})
    assert not {"piper", "vosk"} & set(probed)
    probed.clear()
    runtime_dependencies.missing(task_units(DEFAULT_REGISTRY["s5_voice"]), {})
    assert {"piper", "vosk"} <= set(probed)


def test_task_explicit_domain_reaches_preflight_unchanged(tmp_path):
    manager = World().manager(tmp_path)
    options, calls = {"domain": "asr"}, []
    manager.dependency_check = lambda units, opts: calls.append(opts) or []
    assert manager.set_feature("s10_ai_providers", True, options=options)["ok"]
    assert calls == [options] and options == {"domain": "asr"}
