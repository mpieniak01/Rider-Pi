import json
import os
import time

import pytest
from flask import Flask

from apps.compute.client import ComputeError
from common.service_catalog import DEFAULT_REGISTRY, task_units
from services import compute_config, compute_operations
from services.api_core import compute_api
from services.core.features import FeatureManager, NullPublisher


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("RIDER_COMPUTE_CONFIG", str(tmp_path / "compute.json"))
    monkeypatch.setenv("RIDER_COMPUTE_STATUS", str(tmp_path / "status.json"))
    monkeypatch.setenv("FEATURE_STATE_PATH", str(tmp_path / "feature_state.json"))
    monkeypatch.setenv("RIDER_COMPUTE_TOKEN", "fixture-only")


def configured():
    row = compute_config.configure("http://127.0.0.1:18881", "fixture")
    return compute_config.select("venom", row["revision"])


def app():
    app = Flask(__name__)
    app.add_url_rule("/config", view_func=compute_api.config_handler, methods=["GET", "POST", "OPTIONS"])
    app.add_url_rule("/status", view_func=compute_api.status_handler)
    app.add_url_rule("/tasks/<task>", view_func=compute_api.task_handler, methods=["POST"])
    return app


def test_configuration_is_one_atomic_private_point_without_side_effects():
    assert compute_config.selected_executor() is None
    selected = configured()
    private = compute_config.selected_executor()
    assert selected["selected_executor"] == "venom" and selected["revision"] == 2
    assert private["token"] == "fixture-only"
    public = json.dumps(selected)
    assert "fixture-only" not in public and "http://" not in public
    assert compute_config.config_path().stat().st_mode & 0o777 == 0o600
    assert not compute_config.status_path().exists()
    compute_config.select(None, selected["revision"])
    assert compute_config.selected_executor() is None


@pytest.mark.parametrize(
    "url", ["file:///tmp", "http://u:p@host", "http://host?a=b", "http://host/path", "http://host:90000"]
)
def test_invalid_executor_url_is_never_persisted(url):
    with pytest.raises(ValueError):
        compute_config.configure(url, "fixture")
    assert not compute_config.config_path().exists()


def test_conflict_and_unknown_executor_do_not_overwrite_selection():
    selected = configured()
    for executor, revision, error in [
        (None, 0, "compute_configuration_conflict"),
        ("other", selected["revision"], "compute_executor_unknown"),
    ]:
        with pytest.raises(ValueError, match=error):
            compute_config.select(executor, revision)
    assert compute_config.snapshot() == selected


def test_selected_missing_credential_is_explicit_not_local_fallback(monkeypatch):
    configured()
    monkeypatch.delenv("RIDER_COMPUTE_TOKEN")
    assert compute_config.snapshot()["executors"][0]["credential_configured"] is False
    with pytest.raises(ValueError, match="compute_credentials_unavailable"):
        compute_config.selected_executor()


def test_executor_changes_require_stopped_goals_and_cli_uses_same_guard():
    selected = configured()
    path = os.environ["FEATURE_STATE_PATH"]
    with open(path, "w") as stream:
        json.dump({"requested": ["s12_venom_vision"]}, stream)
    with pytest.raises(ValueError, match="compute_stop_goals_first"):
        compute_config.select(None, selected["revision"])
    with pytest.raises(ValueError, match="compute_stop_goals_first"):
        compute_config.configure("http://other.invalid", "fixture")
    assert compute_config.snapshot() == selected


def test_status_preserves_source_age_and_filters_sensitive_data(monkeypatch):
    selected = configured()
    assert compute_config.record_status(
        "vision",
        {
            "state": "running",
            "observed_at": time.time(),
            "captured_at": 100.0,
            "data": {"text": "scene", "token": "private"},
            "url": "private",
            "token": "private",
            "metrics": {"source_age_ms": 900},
        },
        revision=selected["revision"],
    )
    raw = compute_config.observed_status()
    assert raw["domains"]["vision"]["captured_at"] == 100
    assert raw["domains"]["vision"]["stale"] is False
    assert "private" not in json.dumps(raw)
    now = time.time()
    monkeypatch.setattr(compute_config.time, "time", lambda: now + 30)
    assert compute_config.observed_status()["domains"]["vision"]["stale"] is True


def test_old_revision_status_is_dropped_and_off_is_explicit():
    row = configured()
    assert not compute_config.record_status("vision", {"state": "running"}, revision=0)
    compute_config.record_status("vision", {"state": "off"}, revision=row["revision"])
    assert compute_config.observed_status()["domains"]["vision"]["state"] == "off"


def test_new_goals_are_nonmoving_and_do_not_start_pi_ai_models():
    configured()
    vision = DEFAULT_REGISTRY["s12_venom_vision"]
    voice = DEFAULT_REGISTRY["s13_venom_voice"]
    assert not vision.can_move and not voice.can_move
    assert "rider-voice-web.service" not in task_units(voice)
    assert "rider-obstacle.service" not in task_units(vision)
    assert "rider-vision.service" not in task_units(vision)


def test_goal_start_off_uses_existing_reference_counted_service_manager(tmp_path):
    configured()
    states = {}
    calls = []

    def run(unit, action):
        calls.append((unit, action))
        states[unit] = "active" if action == "start" else "inactive"
        return {"ok": True}

    manager = FeatureManager(
        runner=run,
        status_fn=lambda unit: {"active": states.get(unit, "inactive"), "load": "loaded"},
        publisher=NullPublisher(),
        state_path=os.environ["FEATURE_STATE_PATH"],
        dependency_check=lambda *_: [],
        safety_status=lambda: {"state": "DISARMED", "ready": True},
        safety_stop=lambda *_: (_ for _ in ()).throw(AssertionError("no actuator stop")),
    )
    assert manager.set_feature("s13_venom_voice", True)["ok"]
    assert ("rider-voice.service", "start") in calls
    assert not any(unit == "rider-voice-web.service" for unit, _ in calls)
    assert manager.set_feature("s13_venom_voice", False)["ok"]
    assert ("rider-voice.service", "stop") in calls


def test_config_api_and_cli_have_same_revision_and_no_secret():
    selected = configured()
    with app().test_client() as client:
        assert client.get("/config").json == selected
        assert client.post("/config", json={"executor_id": None, "revision": 0}).status_code == 409
        result = client.post("/config", json={"executor_id": None, "revision": selected["revision"]})
        assert result.status_code == 200 and result.json["selected_executor"] is None
        assert "fixture-only" not in result.get_data(as_text=True)


def test_panel_task_and_chat_share_client_close_no_capture_or_play(monkeypatch):
    configured()
    calls = []

    class Client:
        def __init__(self, *args, **kwargs):
            calls.append(("client", kwargs))

        def submit(self, task, data, mime, metadata, params=None):
            calls.append((task, data, metadata))
            return "job"

        def result(self, *_args, **_kwargs):
            return {"state": "succeeded", "data": {"text": "reply"}, "quality": {"simulated": True}}

        def close(self):
            calls.append(("close",))

    result, binary = compute_operations.execute(
        "text.respond", b"hello", "text/plain; charset=utf-8", client_factory=Client
    )
    assert result["data"]["text"] == "reply" and binary is None
    assert calls[-1] == ("close",)
    assert calls[0][1]["client_id"] == "panel"


def test_api_task_rejects_invalid_params_and_reports_offline(monkeypatch):
    configured()
    with app().test_client() as client:
        assert client.post("/tasks/text.respond", data=b"a", headers={"X-Rider-Params": "[]"}).status_code == 400

        def unavailable(*_):
            raise ComputeError("compute_transport_error", 503)

        monkeypatch.setattr(compute_api, "execute", unavailable)
        response = client.post("/tasks/text.respond", data=b"a", content_type="text/plain")
        assert response.status_code == 503 and response.json["error"] == "compute_transport_error"


@pytest.mark.parametrize("available", [True, False])
def test_chat_uses_compute_and_never_falls_back_to_legacy(monkeypatch, available):
    from services.api_core import chat_glue

    configured()

    def no_legacy(*_args):
        raise AssertionError("selected compute must not call local or PC chat")

    def execute(task, payload, content_type, params):
        assert (task, payload, content_type, params) == (
            "text.respond",
            b"hello",
            "text/plain; charset=utf-8",
            {"language": "pl"},
        )
        if not available:
            raise ComputeError("compute_transport_error", 503)
        return {"state": "succeeded", "data": {"text": "reply"}}, None

    monkeypatch.setattr(compute_operations, "execute", execute)
    monkeypatch.setattr(chat_glue, "_try_local_agent", no_legacy)
    monkeypatch.setattr(chat_glue, "_remote_reply", no_legacy)
    monkeypatch.setattr(chat_glue, "_store_add", lambda item: item)
    web = Flask(__name__)
    chat_glue.register(web)
    with web.test_client() as client:
        response = client.post("/api/chat/send", json={"text": "hello"})
        assert response.status_code == (200 if available else 503)
        if available:
            assert response.json["reply"] == "reply" and response.json["source"] == "venom"
        else:
            assert response.json["error"] == "compute_transport_error"


def test_invalid_compute_configuration_is_not_a_legacy_provider_status(monkeypatch):
    from services.api_core import provider_observation

    def invalid():
        raise ValueError("compute_configuration_invalid")

    def no_hardware(*_args):
        raise AssertionError("invalid compute configuration cannot trigger legacy probes")

    monkeypatch.setattr(compute_config, "observed_status", invalid)
    monkeypatch.setattr(provider_observation.registry, "get_state_snapshot", lambda: {})
    monkeypatch.setattr(provider_observation.registry, "get_health_snapshot", lambda: {})
    monkeypatch.setattr(provider_observation.task_runtime, "read_status", no_hardware)
    monkeypatch.setattr(provider_observation.systemd_ctrl, "status", no_hardware)
    result = provider_observation.snapshot()
    assert result["partial"] is True
    assert all(not row["ready"] and row["effective"] == "unavailable" for row in result["domains"].values())
    assert all(row["error"] == "compute_configuration_unavailable" for row in result["domains"].values())
