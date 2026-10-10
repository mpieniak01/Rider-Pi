"""Selected voice domains, dependencies and producer acknowledgements use only fakes."""

from __future__ import annotations

import importlib.util
import json
import time
from types import SimpleNamespace

import pytest
from test_task_lifecycle import World

from apps.voice import domain_profiles, domain_worker, profile_state
from common import runtime_dependencies, task_runtime
from common.service_catalog import CAMERA_UNITS, DEFAULT_REGISTRY, task_resources, task_units


def models(tmp_path, monkeypatch):
    vosk = tmp_path / "vosk"
    vosk.mkdir()
    piper = tmp_path / "voice.onnx"
    piper.write_bytes(b"fake")
    piper.with_suffix(".onnx.json").write_text("{}")
    monkeypatch.setenv("VOSK_MODEL", str(vosk))
    monkeypatch.setenv("PIPER_MODEL", str(piper))
    monkeypatch.setenv("VOICE_WEB_LLM_PROVIDER", "stub")


def healthy(domains):
    return {
        "ready": bool(domains),
        "domains": sorted(domains),
        "missing": [],
        "capabilities": {domain: {"ready": True, "model_loaded": True} for domain in domains},
    }


@pytest.mark.parametrize("domain,module", [("asr", "vosk"), ("tts", "piper")])
def test_domain_preflight_probes_only_selected_backend(tmp_path, monkeypatch, domain, module):
    models(tmp_path, monkeypatch)
    calls = []
    result = domain_profiles.availability({domain}, find_spec=lambda name: calls.append(name) or object())
    assert result["ready"] and calls == [module]


def test_full_voice_unavailable_when_chat_disabled(tmp_path, monkeypatch):
    models(tmp_path, monkeypatch)
    result = domain_profiles.availability(domain_profiles.expand("voice"), find_spec=lambda name: object())
    assert result["ready"] is False
    assert result["missing"] == ["chat_backend_disabled"]
    assert result["capabilities"]["asr"]["ready"] and result["capabilities"]["tts"]["ready"]
    assert not result["capabilities"]["chat"]["ready"]


def test_asr_missing_model_and_module_are_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("VOSK_MODEL", str(tmp_path / "absent"))
    result = domain_profiles.availability({"asr"}, find_spec=lambda name: None)
    assert set(result["missing"]) == {"asr_model_unavailable", "vosk"}
    assert result["capabilities"]["asr"]["ready"] is False


def test_journal_unions_only_live_requested_domains(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "features": [
                    {
                        "name": "s5_voice",
                        "requested": True,
                        "state": "starting",
                        "members": ["rider-voice-web.service"],
                        "options": {"domain": "asr"},
                    },
                    {
                        "name": "s10_ai_providers",
                        "requested": True,
                        "state": "ready",
                        "members": ["rider-voice-web.service"],
                        "options": {"domain": "tts"},
                    },
                    {
                        "name": "s5_voice",
                        "requested": False,
                        "state": "ready",
                        "members": ["rider-voice-web.service"],
                        "options": {"domain": "voice"},
                    },
                ]
            }
        )
    )
    assert domain_profiles.requested_domains(path) == {"asr", "tts"}
    path.write_text("corrupt")
    assert domain_profiles.requested_domains(path) == set()


@pytest.mark.parametrize("domain", ["asr", "tts"])
def test_worker_imports_only_selected_backend_and_releases_other_cache(monkeypatch, domain):
    calls, snapshots = [], []
    legacy = SimpleNamespace(
        _load_vosk_backend=lambda: calls.append("asr") or True,
        _load_piper_backend=lambda: calls.append("tts") or True,
        _get_local_vosk_model=lambda: calls.append("asr_model") or object(),
        _get_local_piper_voice=lambda: calls.append("tts_model") or object(),
        _local_vosk_model=object(),
        _local_piper_voice=object(),
    )
    monkeypatch.setattr(domain_worker, "availability", healthy)
    monkeypatch.setattr(domain_worker, "write_status", snapshots.append)
    result = domain_worker.update_profile(legacy, {domain})
    assert calls == [domain, domain + "_model"] and result["ready"] and snapshots == [result]
    assert result["capabilities"][domain]["model_loaded"] is True
    assert getattr(legacy, "_local_piper_voice" if domain == "asr" else "_local_vosk_model") is None


def test_worker_failed_backend_import_is_not_ready(monkeypatch):
    monkeypatch.setattr(domain_worker, "availability", healthy)
    monkeypatch.setattr(domain_worker, "write_status", lambda status: None)
    legacy = SimpleNamespace(_load_vosk_backend=lambda: False, _local_vosk_model=None, _local_piper_voice=None)
    status = domain_worker.update_profile(legacy, {"asr"})
    assert status["missing"] == ["asr_model_load_failed:ImportError"]
    assert not status["ready"] and not status["capabilities"]["asr"]["ready"]


def test_worker_request_admission_requires_domain_and_actual_heartbeat(monkeypatch):
    calls = []
    legacy = SimpleNamespace(
        _load_config=lambda: calls.append("config"),
        api_asr=lambda: {"ok": True},
        api_tts=lambda: {"ok": True},
        api_tts_test=lambda: {"ok": True},
        api_chat_local=lambda: {"ok": True},
    )
    monkeypatch.setattr(domain_worker, "requested_domains", lambda: {"asr"})
    monkeypatch.setattr(domain_worker, "availability", healthy)
    status = {"stale": False, **healthy({"asr"})}
    client = domain_worker.create_app(legacy, profile_status=lambda: status).test_client()
    assert client.post("/api/asr").status_code == 200 and calls == ["config"]
    assert client.post("/api/tts").status_code == 503 and calls == ["config"]
    status["capabilities"]["asr"]["ready"] = False
    assert client.post("/api/asr").status_code == 503
    assert client.get("/healthz").status_code == 503
    status["capabilities"]["asr"]["ready"] = True
    status["stale"] = True
    assert client.post("/api/asr").status_code == 503


def test_atomic_heartbeat_is_bounded_readonly_and_stale_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("FEATURE_STATE_PATH", str(tmp_path / "state.json"))
    profile_state.write_status(healthy({"tts"}))
    status = task_runtime.read_status("rider-voice-web.service", root=tmp_path)
    assert not status["stale"] and status["domains"] == ["tts"]
    path = tmp_path / "rider-voice-web.service.json"
    status["observed_at"] = time.time() - 10
    path.write_text(json.dumps(status))
    assert task_runtime.read_status("rider-voice-web.service", root=tmp_path)["stale"]


def test_task_waits_for_exact_motion_producer_acceptance(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    manager.producer_status = lambda unit: {"stale": True}
    result = manager.set_feature("face_tracking", True)
    assert result["ok"] and result["task"]["state"] == "starting" and not result["task"]["ready"]
    intent = manager._service_intents()["rider-tracking-controller.service"]
    snapshot = {
        "unit": "rider-tracking-controller.service",
        "stale": False,
        "accepted": True,
        "active": True,
        "generation": intent["generation"],
        "request_id": "wrong",
    }
    manager.producer_status = lambda unit: snapshot
    task = next(task for task in manager.describe_features() if task["name"] == "s3_follow_me_face")
    assert not task["ready"]
    snapshot["request_id"] = intent["request_id"]
    task = next(task for task in manager.describe_features() if task["name"] == "s3_follow_me_face")
    assert task["ready"] and task["state"] == "ready"


def test_lost_producer_heartbeat_becomes_partial_after_start_deadline(tmp_path):
    manager = World().manager(tmp_path)
    manager.producer_status = lambda unit: {"stale": True}
    assert manager.set_feature("face_tracking", True)["ok"]
    manager._started_at["s3_follow_me_face"] = time.monotonic() - 6
    task = next(task for task in manager.describe_features() if task["name"] == "s3_follow_me_face")
    assert task["state"] == "partial" and task["error"] == "producer_acceptance_unavailable"


def test_shared_asr_tts_profiles_start_one_worker_and_stop_last(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    assert manager.set_feature("s5_voice", True, options={"domain": "asr"})["ok"]
    assert manager.set_feature("s10_ai_providers", True, options={"domain": "tts"})["ok"]
    assert world.actions.count(("rider-voice-web.service", "start")) == 1
    assert not any(unit == "rider-voice.service" for unit, _ in world.actions)
    resources = manager.resource_consumers()
    assert resources["mic"] == ["s5_voice"] and resources["speaker"] == ["s10_ai_providers"]
    assert manager.set_feature("s5_voice", False)["ok"]
    assert "rider-voice-web.service" in world.active
    assert manager.set_feature("s10_ai_providers", False)["ok"]
    assert "rider-voice-web.service" not in world.active


def test_missing_profile_dependency_fails_before_any_service_start(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    manager.dependency_check = lambda units, options: ["vosk"]
    result = manager.set_feature("s5_voice", True, options={"domain": "asr"})
    assert result["error"] == "runtime_dependencies_missing" and not world.actions
    task = next(task for task in manager.describe_features() if task["name"] == "s5_voice")
    assert task["state"] == "failed" and task["missing_runtime_dependencies"] == ["vosk"]


def test_module_preflight_does_not_probe_inactive_vision_or_tts(monkeypatch):
    calls = []
    monkeypatch.setattr(importlib.util, "find_spec", lambda module: calls.append(module) or object())
    units = task_units(DEFAULT_REGISTRY["s5_voice"], {"domain": "asr"})
    assert runtime_dependencies.missing(units, {"domain": "asr"}) == []
    assert "vosk" in calls and not {"piper", "mediapipe", "cv2"} & set(calls)


def test_asr_resources_do_not_claim_speaker():
    resources = task_resources(DEFAULT_REGISTRY["s5_voice"], {"domain": "asr"})
    assert "mic" in resources and "speaker" not in resources


def test_full_voice_has_backend_before_cli():
    units = task_units(DEFAULT_REGISTRY["s5_voice"])
    assert units.index("rider-voice-web.service") < units.index("rider-voice.service")
    assert not set(CAMERA_UNITS) & set(units)


def test_selected_tts_uses_local_default_without_cloud_or_asr(monkeypatch):
    import io
    import wave

    monkeypatch.setenv("VOICE_WEB_LOAD_PROFILE", "0")
    monkeypatch.setenv("VOICE_DOMAIN_CONFIG", "voice_local_file.toml")
    from apps.voice import config, web

    config_paths = []
    monkeypatch.setattr(config, "load", lambda path: config_paths.append(path) or {"tts": {"backend": "local"}})
    monkeypatch.setattr(web, "_load_piper_backend", lambda: True)
    monkeypatch.setattr(web, "_get_local_piper_voice", lambda path: object())
    data = io.BytesIO()
    with wave.open(data, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 32)
    monkeypatch.setattr(web, "_piper_synthesize_wav_bytes", lambda *args: (data.getvalue(), 16000))
    monkeypatch.setattr(domain_worker, "requested_domains", lambda: {"tts"})
    monkeypatch.setattr(domain_worker, "availability", healthy)
    client = domain_worker.create_app(web, profile_status=lambda: {"stale": False, **healthy({"tts"})}).test_client()
    response = client.post("/api/tts", json={"text": "fixture"})
    assert response.status_code == 200 and response.data[:4] == b"RIFF"
    assert config_paths == ["voice_local_file.toml"]
    assert client.post("/api/tts", json={"text": "fixture", "backend": "openai"}).status_code == 400


def test_voice_admin_claims_only_selected_domain_resource(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    assert manager.service_action("rider-voice-web.service", "start", control={"domain": "tts"})["ok"]
    resources = manager.resource_consumers()
    assert resources["speaker"] == ["admin:rider-voice-web.service"] and "mic" not in resources


def test_motion_readiness_rejects_ack_from_previous_pid(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    assert manager.set_feature("face_tracking", True)["ok"]
    original = manager.status_fn
    manager.status_fn = lambda unit: {**original(unit), "pid": 123}
    intent = manager._service_intents()["rider-tracking-controller.service"]
    observed = {
        "accepted": True,
        "active": True,
        "stale": False,
        "generation": intent["generation"],
        "request_id": intent["request_id"],
        "pid": 122,
    }
    manager.producer_status = lambda unit: observed
    task = next(task for task in manager.describe_features() if task["name"] == "s3_follow_me_face")
    assert not task["ready"]
    observed["pid"] = 123
    task = next(task for task in manager.describe_features() if task["name"] == "s3_follow_me_face")
    assert task["ready"]
