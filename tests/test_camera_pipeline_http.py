"""Full Flask negotiation regressions using the real camera and task controllers."""

from __future__ import annotations

import os

import pytest

from apps.camera.pipeline_runtime import write_status
from common.service_catalog import DEFAULT_REGISTRY, task_units
from services import camera_pipeline_store as store
from services.api_core import features_api
from services.api_server import app
from services.camera_pipeline import CameraPipeline
from services.core.features import FeatureManager, NullPublisher

PATH = "/api/resource/camera/pipeline"
ACCEPT = {"Accept": "application/vnd.rider.api+json;version=1"}
CAPABILITIES = {
    "analysis_locations": ["local", "venom"],
    "local_engines": ["canny"],
    "remote_transports": ["snapshots", "mjpeg"],
    "stream_drive_supported": True,
    "local_drive_supported": False,
}


def command(action, request_id, revision=1, profile=None):
    body = {"contract_version": 1, "request_id": request_id, "expected_revision": revision, "action": action}
    if profile is not None:
        body["profile"] = profile
    return body


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("RIDER_CAMERA_PIPELINE_CONFIG", str(tmp_path / "camera.json"))
    monkeypatch.setenv("RIDER_CAMERA_PIPELINE_RUNTIME", str(tmp_path / "runtime"))
    units, calls = set(task_units(DEFAULT_REGISTRY["s0_core"], {})), []
    epoch = 0

    def runner(unit, action):
        nonlocal epoch
        calls.append((unit, action))
        (units.add if action == "start" else units.discard)(unit)
        if unit == "camera-capture@raw.service":
            epoch += int(action == "start")
            config = store.snapshot()
            write_status(
                {
                    "state": "starting" if action == "start" else "stopped",
                    "active_profile": config["profile"] if action == "start" else None,
                    "pipeline_revision": config["revision"],
                    "pid": os.getpid(),
                    "camera_session": "camera-" + str(epoch),
                    "transport_epoch": epoch,
                    "latest_frame": None,
                    "error": None,
                }
            )
        return {"ok": True, "unit": unit, "action": action}

    manager = FeatureManager(
        runner=runner,
        status_fn=lambda unit: {
            "unit": unit,
            "load": "loaded",
            "active": "active" if unit in units else "inactive",
            "pid": os.getpid() if unit in units else 0,
        },
        state_path=tmp_path / "goals.json",
        publisher=NullPublisher(),
        dependency_check=lambda *_: [],
        safety_status=lambda: {"moving": False, "owner": "manual", "output": {"lx": 0, "az": 0}},
        safety_stop=lambda *_: pytest.fail("passive camera operation requested motor STOP"),
    )
    controller = CameraPipeline(manager, capability_fn=lambda: CAPABILITIES)
    monkeypatch.setattr(features_api, "feature_manager", manager)
    monkeypatch.setitem(app.extensions, "rider_camera_pipeline", controller)
    with app.test_client() as test_client:
        yield test_client, manager, calls


def post(client, body):
    return client.post(PATH, json=body, headers=ACCEPT)


def receipt(response, action, request_id, ack_kind):
    assert response.status_code == 200, response.get_json()
    assert response.headers["Content-Type"] == ACCEPT["Accept"]
    body = response.get_json()
    assert body["meta"]["contract_id"] == "rider.camera_pipeline"
    assert body["ok"] is True and body["error"] is None
    assert body["operation"] == {
        "request_id": request_id,
        "action": action,
        "target": "camera",
        "status": "executed",
        "confirmed": True,
        "ack_kind": ack_kind,
        "ack": None,
        "actuation": False,
        "physical_completion": "not_applicable",
    }
    return body["data"]


def test_full_app_start_configure_stop_receipts_preserve_real_source_state(client):
    test_client, manager, calls = client
    observed = test_client.get(PATH, headers=ACCEPT)
    assert observed.status_code == 200 and observed.get_json()["operation"] is None
    assert calls == [] and not store.enabled()
    started = receipt(post(test_client, command("start", "start")), "start", "start", "camera_goal_accepted")
    assert started["state"] == "starting" and started["latest_frame"] is None
    assert started["consumers"] == ["s2_camera_preview"]
    assert manager.resource_consumers()["camera"] == ["s2_camera_preview"]
    profile = dict(store.DEFAULT_PROFILE, remote_transport="mjpeg")
    configured = receipt(
        post(test_client, command("configure", "configure", profile=profile)),
        "configure",
        "configure",
        "configuration_persisted",
    )
    assert configured["revision"] == 2 and configured["active_profile"] == profile
    assert configured["state"] == "starting" and configured["latest_frame"] is None
    assert configured["camera_session"] != started["camera_session"]
    stopped = receipt(post(test_client, command("stop", "stop", revision=2)), "stop", "stop", "camera_source_released")
    assert stopped["state"] == "stopped" and stopped["consumers"] == []
    assert all(unit in {"camera-capture@raw.service", "rider-camera.target"} for unit, _ in calls)
    assert calls.count(("camera-capture@raw.service", "start")) == 2
    assert calls.count(("camera-capture@raw.service", "stop")) == 2


@pytest.mark.parametrize("action", ["start", "configure", "stop"])
def test_full_app_identical_retry_preserves_receipt_without_second_transaction(client, action):
    test_client, _, calls = client
    body = command(action, "retry", profile=dict(store.DEFAULT_PROFILE) if action == "configure" else None)
    first = post(test_client, body)
    assert first.status_code == 200
    before = list(calls)
    second = post(test_client, body)
    assert second.status_code == 200 and second.get_json()["ok"] is True
    assert second.get_json()["operation"] == first.get_json()["operation"]
    assert second.get_json()["data"] == first.get_json()["data"]
    assert calls == before


@pytest.mark.parametrize("conflict", ["request", "revision"])
def test_full_app_conflicts_remain_409_and_never_claim_execution(client, conflict):
    test_client, _, calls = client
    assert post(test_client, command("start", "first")).status_code == 200
    before = list(calls)
    response = post(test_client, command("stop", "first" if conflict == "request" else "stale", revision=9))
    assert response.status_code == 409
    body = response.get_json()
    assert body["ok"] is False
    assert body["error"]["code"] == "camera_pipeline_" + conflict + "_conflict"
    assert body["data"]["current_revision"] == 1
    assert body["operation"]["status"] == "rejected" and body["operation"]["confirmed"] is False
    assert body["operation"]["target"] == "camera" and body["operation"]["ack_kind"] is None
    assert calls == before


def test_full_app_invalid_request_remains_rejected_without_service_actions(client):
    test_client, _, calls = client
    response = post(test_client, command("start", "bad", profile=dict(store.DEFAULT_PROFILE)))
    assert response.status_code == 400 and response.get_json()["ok"] is False
    assert response.get_json()["operation"]["status"] == "rejected"
    assert calls == []


def test_full_app_legacy_json_keeps_domain_response_and_never_arms(client):
    test_client, _, calls = client
    response = test_client.post(PATH, json=command("start", "legacy"))
    assert response.status_code == 200 and response.get_json()["ok"] is True
    assert "meta" not in response.get_json() and response.get_json()["state"] == "starting"
    assert all("motion" not in unit and "navigation" not in unit for unit, _ in calls)


def test_full_app_pipeline_get_is_available_while_real_feature_start_holds_transaction(client, monkeypatch):
    import threading

    test_client, manager, _ = client
    starting, continue_start, finished = threading.Event(), threading.Event(), threading.Event()
    original, results = manager.runner, []

    def delayed(unit, action):
        if unit == "camera-capture@raw.service" and action == "start":
            starting.set()
            assert continue_start.wait(2)
        return original(unit, action)

    def start():
        with app.test_client() as other:
            results.append(post(other, command("start", "concurrent-start")))
        finished.set()

    monkeypatch.setattr(manager, "runner", delayed)
    thread = threading.Thread(target=start)
    thread.start()
    try:
        assert starting.wait(1)
        response = test_client.get(PATH, headers=ACCEPT)
        assert response.status_code == 200 and response.get_json()["meta"]["contract_id"] == "rider.camera_pipeline"
        assert not finished.is_set()
    finally:
        continue_start.set()
        thread.join(3)
    assert finished.is_set() and results[0].status_code == 200


def test_full_app_off_reconciles_source_that_survived_lost_goal_ownership(client, monkeypatch, tmp_path):
    from services import camera_pipeline as domain

    test_client, manager, calls = client
    store.write({"contract_version": 1, "revision": 1, "profile": dict(store.DEFAULT_PROFILE)})
    # The API has no restored goal, while the producer is still running.
    manager.runner("camera-capture@raw.service", "start")
    assert manager.resource_consumers().get("camera", []) == []
    group = tmp_path / "proc" / str(os.getpid()) / "cgroup"
    group.parent.mkdir(parents=True)
    group.write_text("0::/system.slice/camera-capture@raw.service\n")
    monkeypatch.setattr(domain, "PROC_ROOT", tmp_path / "proc")
    # Producer source identity, written by the actual runtime in production.
    import json

    path = store.runtime_path() / "status.json"
    row = json.loads(path.read_text())
    row["camera_session"] = "surviving-source"
    path.write_text(json.dumps(row))
    body = command("stop", "orphan-off")
    stopped = receipt(post(test_client, body), "stop", "orphan-off", "camera_source_released")
    assert stopped["state"] == "stopped" and stopped["consumers"] == []
    assert calls == [("camera-capture@raw.service", "start"), ("camera-capture@raw.service", "stop")]
    before = list(calls)
    receipt(post(test_client, body), "stop", "orphan-off", "camera_source_released")
    assert calls == before
