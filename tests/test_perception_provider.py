"""Provider choice reuses Pi camera profile; no local autonomy policy is replaced."""

import json

import pytest
from flask import Flask

from services import camera_pipeline_store as store, navigation_config, perception_selection
from services.api_core import camera_pipeline_api, navigation_api, rider_routes
from tests.test_camera_pipeline import Manager, command, pipeline
from tests.test_perception_selection import accepted, idle as idle


@pytest.fixture
def camera(idle, monkeypatch, tmp_path):
    monkeypatch.setenv("RIDER_CAMERA_PIPELINE_CONFIG", str(tmp_path / "camera.json"))
    monkeypatch.setenv("RIDER_CAMERA_PIPELINE_RUNTIME", str(tmp_path / "runtime"))
    return pipeline()


def test_provider_and_local_model_change_stays_off_and_revokes_approval(camera):
    accepted()
    response, status = camera.execute(
        command(
            "configure",
            profile={
                "analysis_location": "local",
                "local_engine": "ssd",
                "remote_transport": "snapshots",
            },
        )
    )
    assert status == 200, response
    assert store.snapshot()["profile"]["analysis_location"] == "local"
    assert store.snapshot()["profile"]["local_engine"] == "ssd"
    assert response["state"] == "stopped"
    assert camera.manager.calls == []
    config = navigation_config.snapshot()
    assert config["revision"] == 1
    assert config["mode"] == "observe"
    assert config["calibration_id"] == config["model_sha256"] == ""
    assert config["avoidance"]["sweep_verified"] is False


def test_provider_change_resumes_only_existing_passive_camera_demand(camera):
    camera.manager.consumers = ["s2_camera_preview"]
    camera.manager.units.add(Manager.PREVIEW_UNIT)
    result, status = camera.execute(
        command("configure", profile=dict(store.DEFAULT_PROFILE, analysis_location="local"))
    )
    assert status == 200, result
    assert camera.manager.calls == [("s2_camera_preview", False), ("s2_camera_preview", True)]
    assert camera.manager.consumers == ["s2_camera_preview"]


@pytest.mark.parametrize(
    "patch",
    [
        {"state": "ARMED"},
        {"moving": True},
        {"state": "UNKNOWN"},
        {"stale": True},
    ],
)
def test_provider_switch_never_stops_active_or_unknown_control(camera, idle, patch):
    idle[0].update(patch)
    result, status = camera.execute(
        command("configure", profile=dict(store.DEFAULT_PROFILE, analysis_location="local"))
    )
    assert status == 409
    assert result["error"] == "navigation_model_requires_idle_disarmed"
    assert camera.manager.calls == []
    assert not store.enabled()


def test_local_engine_change_and_active_loop_require_explicit_stop(camera, idle):
    idle[1]["requested"] = ["s15_venom_perception"]
    idle[2].write_text(json.dumps(idle[1]))
    result, status = camera.execute(command("configure", profile=dict(store.DEFAULT_PROFILE, local_engine="ssd")))
    assert status == 409
    assert result["error"] == "navigation_model_stop_loops_first"
    assert not store.enabled()
    assert camera.manager.calls == []


def test_failed_camera_profile_write_cannot_restore_old_driving_acceptance(camera, monkeypatch):
    accepted()

    def fail(_):
        raise OSError("inert disk error")

    monkeypatch.setattr(store, "write", fail)
    result, status = camera.execute(
        command("configure", profile=dict(store.DEFAULT_PROFILE, analysis_location="local"))
    )
    assert status == 503
    assert result["error"] == "camera_pipeline_persistence_failed"
    assert navigation_config.snapshot()["mode"] == "observe"
    assert navigation_config.snapshot()["verified"] is False
    assert camera.manager.calls == []


def test_local_catalog_api_does_not_access_host_or_expose_local_paths(camera, monkeypatch):
    monkeypatch.setattr(camera_pipeline_api, "_pipeline", lambda: camera)
    app = Flask(__name__)
    rider_routes.register_compute(app)
    with app.test_client() as client:
        response = client.get("/api/navigation/local-models")
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert response.json["provider"] == "venom"
        assert {model["id"] for model in response.json["models"]} == {"local-canny", "local-ssd", "local-tflite"}
        assert camera.manager.calls == []
