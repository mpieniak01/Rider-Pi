"""Atomic configuration and fake producer/peer snapshots, without network or models."""

from __future__ import annotations

import json
import time
from copy import deepcopy

import pytest
from flask import Flask

from apps.vision import ai_mode_adapter as vision_adapter
from apps.voice import ai_mode_adapter as voice_adapter
from common import ai_mode, provider_state
from services import provider_registry as registry, provider_watchdog
from services.api_core import http_contract, provider_api, provider_observation


@pytest.fixture
def registry_world(monkeypatch, tmp_path):
    path = tmp_path / "provider.json"
    monkeypatch.setattr(registry, "STATE_FILE", path)
    monkeypatch.setattr(provider_state, "STATE_FILE", path)
    monkeypatch.setattr(registry, "_domains", {domain: registry._default_domain_state() for domain in registry.DOMAINS})
    monkeypatch.setattr(registry, "_pc_health", {"reachable": False, "updated_ts": 0.0})
    monkeypatch.setattr(registry, "_load_error", None)
    monkeypatch.setattr(registry, "_pc_base_url", "http://fixture.invalid:8000")
    monkeypatch.setattr(provider_watchdog, "_fallbacked_domains", set())
    published = []
    monkeypatch.setattr(registry, "_publish_provider_state_event", lambda *args: published.append(args))
    return path, published


def test_named_domain_persists_without_global_or_other_domain_change(registry_world, monkeypatch):
    path, events = registry_world
    monkeypatch.setattr(ai_mode, "_current_mode", "local")
    state, changed = registry.set_domain_mode("vision", "pc")
    assert changed
    assert state["mode"] == "pc"
    assert ai_mode.get_mode() == "local"
    assert registry.get_domain_state("voice")["mode"] == "local"
    assert registry.get_domain_state("text")["mode"] == "local"
    assert json.loads(path.read_text())["domains"]["vision"]["mode"] == "pc"
    assert len(events) == 1
    assert vision_adapter._provider_mode() == "pc"
    assert voice_adapter._provider_mode() == "local"


def test_failed_persistence_restores_memory_and_does_not_publish(registry_world, monkeypatch):
    _, events = registry_world
    previous = deepcopy(registry._domains)

    def failed():
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(registry, "_save_state", failed)
    with pytest.raises(OSError):
        registry.set_domain_mode("voice", "pc")
    assert registry._domains == previous
    assert not events
    with pytest.raises(OSError):
        registry.set_all_domain_modes("pc")
    assert registry._domains == previous
    assert not events


def test_global_is_explicit_atomic_and_invalid_file_does_not_enable_local(registry_world):
    path, _ = registry_world
    registry.set_all_domain_modes("pc")
    assert all(row["mode"] == "pc" for row in json.loads(path.read_text())["domains"].values())
    path.write_text("{broken")
    assert provider_state.get_domain_mode("voice") is None
    assert voice_adapter.should_run_local_asr() is False
    assert vision_adapter.should_run_local_detectors() is False


def test_aliases_and_text_do_not_become_voice(registry_world):
    registry.set_domain_mode("text", "pc")
    assert provider_state.get_domain_mode("asr") == "local"
    assert provider_state.get_domain_mode("tts") == "local"
    assert voice_adapter.should_run_local_asr()
    assert not voice_adapter.should_run_local_nlu()


def test_heartbeat_cycles_do_not_renew_receipt_or_change_requested_routing(registry_world, monkeypatch):
    monkeypatch.setattr(registry, "_now", lambda: 1000.0)
    monkeypatch.setattr(provider_watchdog.time, "time", lambda: 1000.0)
    registry.set_domain_mode("vision", "pc")
    registry.update_pc_health(reachable=True, status="online", received_at=999.0)
    assert provider_watchdog._heartbeat_only_cycle(0) == 0
    assert registry._pc_health["updated_ts"] == 1000
    monkeypatch.setattr(provider_watchdog.time, "time", lambda: 1200.0)
    monkeypatch.setattr(registry, "_now", lambda: 1200.0)
    assert provider_watchdog._heartbeat_only_cycle(3) == 4
    assert registry._pc_health["updated_ts"] == 1000
    assert registry._pc_health["received_at"] == 999
    assert registry.get_domain_state("vision")["mode"] == "pc"
    assert registry.get_health_snapshot()["stale"]


def test_provider_ready_requires_actual_matching_backend_not_peer_http(registry_world):
    now = time.time()
    registry.set_domain_mode("vision", "pc")
    registry.update_pc_health(reachable=True, status="online", received_at=now)
    worker = {
        "pid": 321,
        "observed_at": now,
        "domains": ["asr", "tts", "chat"],
        "capabilities": {
            "asr": {"ready": True, "model_loaded": True},
            "tts": {"ready": False, "model_loaded": False},
            "chat": {"ready": True, "backend": "real-text"},
        },
    }
    unit = {"pid": 321, "active": "active"}
    rows = provider_observation.snapshot(worker=worker, unit=unit)["domains"]
    assert rows["text"]["ready"]
    assert not rows["voice"]["ready"]
    assert not rows["vision"]["ready"]
    assert rows["voice"]["backend_state"]["capabilities"]["asr"]["ready"]
    assert not provider_observation.snapshot(worker=worker, unit={"pid": 999, "active": "active"})["domains"]["text"][
        "ready"
    ]


def test_patch_truthful_success_and_persistence_failure_http(registry_world, monkeypatch):
    app = Flask(__name__)
    http_contract.install(app, after_request=True)
    app.add_url_rule("/api/providers/<domain>", view_func=provider_api.provider_domain_handler, methods=["PATCH"])
    client = app.test_client()
    response = client.patch("/api/providers/asr", json={"target": "pc"})
    assert response.get_json()["ok"]
    assert response.get_json()["affected_domains"] == ["voice"]
    assert registry.get_domain_state("text")["mode"] == "local"
    response = client.patch(
        "/api/providers/text", json={"target": "pc"}, headers={"Accept": "application/vnd.rider.api+json;version=1"}
    )
    assert response.get_json()["operation"]["ack_kind"] == "configuration_persisted"

    def failed():
        raise OSError("synthetic")

    monkeypatch.setattr(registry, "_save_state", failed)
    response = client.patch("/api/providers/vision", json={"target": "pc"})
    assert response.status_code == 503
    assert response.get_json()["persisted"] is False
    assert registry.get_domain_state("vision")["mode"] == "local"


def test_peer_address_and_heartbeat_are_one_transaction(registry_world, monkeypatch):
    previous = registry.get_state_snapshot()

    def failed():
        raise OSError("synthetic")

    monkeypatch.setattr(registry, "_save_state", failed)
    with pytest.raises(OSError):
        registry.record_pc_heartbeat("https://new-peer.invalid:8000", {})
    assert registry.get_state_snapshot()["pc_base_url"] == previous["pc_base_url"]
    assert registry.get_state_snapshot()["pc_health"] == previous["pc_health"]


@pytest.mark.parametrize("value", [[], {"domains": {"voice": {"mode": "local"}}}])
def test_existing_incomplete_registry_is_not_implicit_local(registry_world, value):
    path, _ = registry_world
    path.write_text(json.dumps(value))
    registry._load_state()
    if isinstance(value, list):
        assert registry.get_state_snapshot()["error"] == "provider_state_invalid"
    assert all(row["mode"] is None for row in registry.get_state_snapshot()["domains"].values())


def test_named_patch_repairs_only_its_domain_and_survives_reload(registry_world):
    path, _ = registry_world
    path.write_text("{broken")
    registry._load_state()
    app = Flask(__name__)
    http_contract.install(app, after_request=True)
    app.add_url_rule("/api/providers/<domain>", view_func=provider_api.provider_domain_handler, methods=["PATCH"])
    response = app.test_client().patch(
        "/api/providers/vision", json={"target": "pc"}, headers={"Accept": "application/vnd.rider.api+json;version=1"}
    )
    assert response.status_code == 200
    assert response.get_json()["operation"]["confirmed"]
    registry._load_state()
    assert registry.get_domain_state("vision")["mode"] == "pc"
    assert provider_state.get_domain_mode("vision") == "pc"
    assert registry.get_domain_state("voice")["mode"] is None
    assert provider_state.get_domain_mode("asr") is None
    assert provider_state.get_domain_mode("text") is None
    assert not voice_adapter.should_run_local_asr()


@pytest.mark.parametrize(
    "failure",
    [{"observed_at": None}, {"observed_at": 990}, {"domains": ["asr"]}, {"simulated": True}, {"source": "echo"}],
)
def test_local_text_requires_selected_fresh_real_worker(registry_world, failure):
    worker = {
        "pid": 321,
        "observed_at": 1000,
        "domains": ["chat"],
        "capabilities": {"chat": {"ready": True, "backend": "real"}},
        **failure,
    }
    result = provider_observation.snapshot(worker=worker, unit={"pid": 321, "active": "active"}, now=1000)
    assert result["domains"]["text"]["ready"] is False


@pytest.mark.parametrize("failure", [{"stale": True}, {"offline": True}, {"simulated": True}, {"source": "mock"}])
def test_peer_health_does_not_override_backend_failure(registry_world, failure):
    registry.set_domain_mode("vision", "pc")
    registry.update_pc_health(
        reachable=True,
        status="online",
        received_at=time.time(),
        capabilities={"vision": {"initialized": True, "ready": True, "observed_at": 1000, **failure}},
    )
    result = provider_observation.snapshot(worker={}, unit={}, now=1000)
    assert result["domains"]["vision"]["ready"] is False
