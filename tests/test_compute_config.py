import json
import os
import time

import pytest
from flask import Flask

from apps.compute.client import ComputeError
from common.service_catalog import DEFAULT_REGISTRY, task_units
from services import compute_config, compute_operations
from services.api_core import compute_api, http_contract, rider_routes
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
    http_contract.install(app, after_request=True)
    rider_routes.register_compute(app)
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


@pytest.mark.parametrize("executor_id", [None, "venom"])
def test_config_envelope_confirms_the_actual_persisted_selection(executor_id):
    selected = configured()
    headers = {"Accept": http_contract.MEDIA_TYPE + ";version=1"}
    with app().test_client() as client:
        response = client.post(
            "/api/compute/config", json={"executor_id": executor_id, "revision": selected["revision"]}, headers=headers
        )
        row = response.get_json()
        assert response.status_code == 200
        assert row["ok"] and row["error"] is None
        assert row["data"] == compute_config.snapshot()
        assert row["data"]["selected_executor"] == executor_id
        assert row["data"]["persisted"] is True
        assert row["meta"]["contract_id"] == "rider.compute"
        assert row["operation"]["status"] == "executed"
        assert row["operation"]["confirmed"] is True
        assert row["operation"]["ack_kind"] == "configuration_persisted"
        assert row["operation"]["actuation"] is False
        observed = client.get("/api/compute/config", headers=headers).get_json()
        assert observed["data"] == row["data"] and observed["operation"] is None
        assert "fixture-only" not in response.get_data(as_text=True)


def test_config_envelope_preserves_conflict_and_persistence_failure(monkeypatch):
    selected = configured()
    headers = {"Accept": http_contract.MEDIA_TYPE + ";version=1"}
    with app().test_client() as client:
        response = client.post("/api/compute/config", json={"executor_id": None, "revision": 0}, headers=headers)
        assert response.status_code == 409
        assert response.get_json()["error"]["code"] == "compute_configuration_conflict"
        assert not response.get_json()["operation"]["confirmed"]

        def disk_failure(*_args):
            raise OSError("fixture disk failure")

        monkeypatch.setattr(compute_config, "_write", disk_failure)
        response = client.post(
            "/api/compute/config", json={"executor_id": None, "revision": selected["revision"]}, headers=headers
        )
        assert response.status_code == 503
        assert response.get_json()["error"]["code"] == "compute_persistence_failed"
        assert not response.get_json()["operation"]["confirmed"]
        assert compute_config.snapshot() == selected


@pytest.mark.parametrize("data,status", [({"persisted": False}, 502), ({"persisted": True, "ok": False}, 200)])
def test_config_envelope_requires_real_successful_persistence(monkeypatch, data, status):
    monkeypatch.setattr(compute_config, "select", lambda *_args: data)
    with app().test_client() as client:
        response = client.post(
            "/api/compute/config",
            json={"executor_id": None, "revision": 0},
            headers={"Accept": http_contract.MEDIA_TYPE + ";version=1"},
        )
        assert response.status_code == status
        row = response.get_json()
        assert not row["ok"] and not row["operation"]["confirmed"]


def test_task_envelope_confirms_a_completed_job_without_changing_legacy_data(monkeypatch):
    configured()
    calls = []
    result = {"protocol_version": 1, "job_id": "fixture_job", "state": "succeeded", "data": {"text": "reply"}}

    class Client:
        def __init__(self, *_args, **_kwargs):
            pass

        def submit(self, *_args, **_kwargs):
            return "fixture_job"

        def result(self, *_args, **_kwargs):
            return result

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(
        compute_api,
        "execute",
        lambda task, data, content_type, params: compute_operations.execute(
            task, data, content_type, params, client_factory=Client
        ),
    )
    with app().test_client() as client:
        legacy = client.post("/api/compute/tasks/text.respond", data=b"hello", content_type="text/plain")
        assert legacy.status_code == 200 and legacy.get_json() == result
        response = client.post(
            "/api/compute/tasks/text.respond",
            data=b"hello",
            content_type="text/plain",
            headers={"Accept": http_contract.MEDIA_TYPE + ";version=1"},
        )
        row = response.get_json()
        assert response.status_code == 200 and row["ok"]
        assert row["data"] == result and row["error"] is None
        assert row["operation"]["status"] == "executed"
        assert row["operation"]["confirmed"] is True
        assert row["operation"]["ack_kind"] == "computation_completed"
        assert row["operation"]["target"] == "text.respond"
        assert row["operation"]["actuation"] is False
        assert calls == ["closed", "closed"]


@pytest.mark.parametrize("status", [400, 409, 429, 503])
def test_task_envelope_preserves_compute_error_status_and_code(monkeypatch, status):
    def failed(*_args):
        raise ComputeError("fixture_compute_error", status)

    monkeypatch.setattr(compute_api, "execute", failed)
    with app().test_client() as client:
        response = client.post(
            "/api/compute/tasks/text.respond",
            data=b"hello",
            content_type="text/plain",
            headers={"Accept": http_contract.MEDIA_TYPE + ";version=1"},
        )
        row = response.get_json()
        assert response.status_code == status
        assert row["error"]["code"] == "fixture_compute_error"
        assert not row["ok"] and not row["operation"]["confirmed"]


@pytest.mark.parametrize("state", ["running", "failed", "unknown"])
def test_task_envelope_does_not_confirm_unfinished_or_unproven_jobs(monkeypatch, state):
    monkeypatch.setattr(compute_api, "execute", lambda *_args: ({"state": state}, None))
    with app().test_client() as client:
        response = client.post(
            "/api/compute/tasks/text.respond",
            data=b"hello",
            content_type="text/plain",
            headers={"Accept": http_contract.MEDIA_TYPE + ";version=1"},
        )
        row = response.get_json()
        assert response.status_code == 502
        assert not row["ok"] and not row["operation"]["confirmed"]


def test_negotiated_compute_wav_stays_binary_and_never_plays_audio(monkeypatch):
    output = b"RIFFfixture"
    monkeypatch.setattr(compute_api, "execute", lambda *_args: ({"state": "succeeded"}, output))
    with app().test_client() as client:
        response = client.post(
            "/api/compute/tasks/audio.synthesize",
            data=b"hello",
            content_type="text/plain",
            headers={"Accept": http_contract.MEDIA_TYPE + ";version=1"},
        )
        assert response.status_code == 200 and response.mimetype == "audio/wav"
        assert response.data == output and not response.is_json


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


@pytest.mark.parametrize("url", ["http://venom-host:8000", "http://10.0.0.1", "http://[2001:db8::1]", None, []])
def test_private_configuration_rejects_plain_http_network_endpoint(url):
    with pytest.raises(ValueError, match="compute_configuration_invalid"):
        compute_config.configure(url, "fixture")
    assert not compute_config.config_path().exists()


@pytest.mark.parametrize(
    "url",
    [
        "https://fixture.invalid:8443",
        "http://localhost:8000",
        "http://[::1]:8000",
        "https://fixture.invalid:8443/api/v1/rider/compute",
        "http://127.0.0.1:18800/api/v1/rider/compute",
    ],
)
def test_private_configuration_accepts_https_or_loopback_only(url):
    result = compute_config.configure(url, "fixture")
    compute_config.select("venom", result["revision"])
    assert compute_config.selected_executor()["url"] == url


def test_insecure_existing_file_is_refused_on_read_and_not_silently_upgraded():
    configured()
    path = compute_config.config_path()
    data = json.loads(path.read_text())
    data["executors"]["venom"]["url"] = "http://venom-host:8000"
    path.write_text(json.dumps(data))
    original = path.read_bytes()
    with pytest.raises(ValueError, match="compute_configuration_invalid"):
        compute_config.selected_executor()
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "conversation_available,conversation_selected,response_ready",
    [(False, True, True), (True, False, True), (True, True, True), (True, True, False)],
)
def test_provider_reads_runner_envelope_and_actual_r2_r3_response_task(
    monkeypatch, conversation_available, conversation_selected, response_ready
):
    from services.api_core import provider_observation
    from tests.test_compute_runners import voice_runner

    selected_config = configured()
    selected = compute_config.selected_executor()
    if not conversation_selected:
        selected["tasks"] = [task for task in selected["tasks"] if task != "conversation.respond"]
    runner, client, _, statuses, _ = voice_runner(selected=selected)
    client.tasks["conversation.respond"] = {"available": conversation_available, "ready": response_ready}
    for row in client.tasks.values():
        row["ready"] = True
    response_task = "conversation.respond" if conversation_available and conversation_selected else "text.respond"
    client.tasks[response_task]["ready"] = response_ready
    if response_task == "conversation.respond":
        client.tasks["text.respond"]["ready"] = False  # A cold R2 model does not block the R3 pipeline.

    def record(observation):
        statuses.append(observation)
        compute_config.record_status("voice", observation, revision=selected_config["revision"])

    def no_legacy_probe(*_):
        pytest.fail("selected compute must not poll legacy services")

    runner.on_status = record
    monkeypatch.setattr(provider_observation.registry, "get_state_snapshot", lambda: {})
    monkeypatch.setattr(provider_observation.registry, "get_health_snapshot", lambda: {})
    monkeypatch.setattr(provider_observation.task_runtime, "read_status", no_legacy_probe)
    monkeypatch.setattr(provider_observation.systemd_ctrl, "status", no_legacy_probe)
    try:
        runner._start({"audio.transcribe", "text.respond", "audio.synthesize"})
        assert statuses[-1]["response_task"] == response_task
        assert "tasks" in statuses[-1]["capabilities"]
        result = provider_observation.snapshot()
        voice = result["domains"]["voice"]
        assert voice["ready"] is response_ready and voice["initialized"] is True
        assert voice["effective"] == ("venom" if response_ready else "unavailable")
        assert result["domains"]["text"]["ready"] is client.tasks["text.respond"]["ready"]
        runner.status("off")
        assert provider_observation.snapshot()["domains"]["voice"]["ready"] is False
    finally:
        runner.close()


@pytest.mark.parametrize("ready", [True, False])
def test_provider_reads_vision_runner_capabilities_tasks(monkeypatch, ready):
    from services.api_core import provider_observation
    from tests.test_compute_runners import vision_runner

    configured()
    selected = compute_config.selected_executor()
    runner, client, _, _, _ = vision_runner([], selected=selected)
    client.tasks["vision.describe"]["ready"] = ready
    runner.on_status = lambda row: compute_config.record_status("vision", row, revision=selected["revision"])
    monkeypatch.setattr(provider_observation.registry, "get_state_snapshot", lambda: {})
    monkeypatch.setattr(provider_observation.registry, "get_health_snapshot", lambda: {})
    try:
        runner._start({"vision.describe"})
        result = provider_observation.snapshot()
        assert result["domains"]["vision"]["ready"] is ready
        assert result["domains"]["vision"]["initialized"] is True
        assert result["domains"]["voice"]["ready"] is False
    finally:
        runner.close()


@pytest.mark.parametrize("language", [{}, []])
def test_transcription_api_returns_400_for_container_language_without_network(monkeypatch, language):
    from apps.compute.client import ComputeClient
    from tests.test_compute_client import Transport, wav

    configured()
    transport = Transport()

    def execute(task, payload, mime, params):
        return compute_operations.execute(
            task,
            payload,
            mime,
            params,
            client_factory=lambda *args, **kwargs: ComputeClient(*args, transport=transport, **kwargs),
        )

    monkeypatch.setattr(compute_api, "execute", execute)
    with app().test_client() as http:
        response = http.post(
            "/tasks/audio.transcribe",
            data=wav(),
            content_type="audio/wav",
            headers={"X-Rider-Params": json.dumps({"language": language})},
        )
    assert response.status_code == 400 and response.json["error"] == "invalid_compute_params"
    assert not transport.calls and transport.closed
    assert compute_operations._panel_lock.acquire(blocking=False)
    compute_operations._panel_lock.release()
