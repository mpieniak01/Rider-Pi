"""Backend files/imports cannot substitute for actual selected model validation."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from test_domains_and_readiness import healthy

from apps.voice import domain_worker


@pytest.mark.parametrize("domain", ["asr", "tts"])
def test_existing_model_with_broken_constructor_stays_unavailable(monkeypatch, domain):
    calls = []

    def corrupt_model():
        calls.append(domain)
        raise RuntimeError("isolated corrupt model")

    legacy = SimpleNamespace(
        _load_vosk_backend=lambda: True,
        _load_piper_backend=lambda: True,
        _get_local_vosk_model=corrupt_model,
        _get_local_piper_voice=corrupt_model,
        _local_vosk_model=None,
        _local_piper_voice=None,
    )
    snapshots = []
    monkeypatch.setattr(domain_worker, "availability", healthy)
    monkeypatch.setattr(domain_worker, "write_status", snapshots.append)
    status = domain_worker.update_profile(legacy, {domain})
    assert calls == [domain]
    assert status["missing"] == [f"{domain}_model_load_failed:RuntimeError"]
    assert status["ready"] is False
    assert status["capabilities"][domain]["ready"] is False
    assert status["capabilities"][domain]["model_loaded"] is False
    assert snapshots == [status]


@pytest.mark.parametrize("domain", ["asr", "tts"])
def test_worker_waits_for_loaded_model_heartbeat(monkeypatch, domain):
    legacy = SimpleNamespace(
        _load_config=lambda: None,
        api_asr=lambda: {"ok": True},
        api_tts=lambda: {"ok": True},
        api_tts_test=lambda: {"ok": True},
        api_chat_local=lambda: {"ok": True},
    )
    monkeypatch.setattr(domain_worker, "requested_domains", lambda: {domain})
    monkeypatch.setattr(domain_worker, "availability", healthy)
    status = {"stale": False, **healthy({domain})}
    status["capabilities"][domain].pop("model_loaded")
    client = domain_worker.create_app(legacy, profile_status=lambda: status).test_client()
    payload = {"text": "fixture", "backend": "local"}
    assert client.post("/api/" + domain, json=payload).status_code == 503
    status["capabilities"][domain]["model_loaded"] = True
    assert client.post("/api/" + domain, json=payload).status_code == 200
