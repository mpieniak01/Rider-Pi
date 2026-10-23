"""No camera, physical BUS, SSH or actuator calls in pipeline regressions."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import time

import numpy as np
import pytest
from flask import Flask

from apps.camera import pipeline_ipc, pipeline_local, pipeline_runtime
from services import camera_pipeline as domain, camera_pipeline_store as store
from services.api_core import camera_pipeline_api


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("RIDER_CAMERA_PIPELINE_CONFIG", str(tmp_path / "camera_pipeline.json"))
    monkeypatch.setenv("RIDER_CAMERA_PIPELINE_RUNTIME", str(tmp_path / "runtime"))
    monkeypatch.setenv("SNAP_DIR", str(tmp_path / "snapshots"))
    monkeypatch.setenv("PREVIEW_ROT", "0")
    monkeypatch.setenv("PREVIEW_FLIP_H", "0")
    monkeypatch.setenv("PREVIEW_FLIP_V", "0")


class Manager:
    PREVIEW_UNIT = "camera-capture@raw.service"

    def __init__(self):
        self.consumers, self.units, self.calls = [], set(), []
        self.safety = {"moving": False, "owner": "manual", "output": {"lx": 0, "az": 0}}

    @contextlib.contextmanager
    def transaction(self):
        yield

    def resource_consumers(self):
        return {"camera": list(self.consumers)}

    def safety_status(self):
        return copy.deepcopy(self.safety)

    def _status(self, unit):
        return {"active": "active" if unit in self.units else "inactive"}

    def _running(self, unit):
        return unit in self.units

    def set_feature(self, name, enabled):
        self.calls.append((name, enabled))
        if enabled:
            if name not in self.consumers:
                self.consumers.append(name)
            self.units.add(self.PREVIEW_UNIT)
        else:
            if name in self.consumers:
                self.consumers.remove(name)
            if name == "s14_venom_navigation":
                self.safety.update(moving=False, output={"lx": 0, "az": 0})
            if not self.consumers:
                self.units.clear()
        return {"ok": True}


CAPS = {
    "analysis_locations": ["local", "venom"],
    "local_engines": ["canny", "ssd", "tflite"],
    "remote_transports": ["snapshots", "mjpeg"],
    "stream_drive_supported": True,
    "local_drive_supported": False,
}


def command(action, *, request_id="request-1", revision=1, profile=None):
    result = {"contract_version": 1, "request_id": request_id, "expected_revision": revision, "action": action}
    if profile is not None:
        result["profile"] = profile
    return result


def pipeline(manager=None):
    return domain.CameraPipeline(manager or Manager(), capability_fn=lambda: CAPS)


def test_default_read_is_passive_and_does_not_create_profile():
    manager = Manager()
    result = pipeline(manager).status()
    assert result["revision"] == 1
    assert result["profile"] == store.DEFAULT_PROFILE
    assert result["state"] == "stopped"
    assert result["active_profile"] is None
    assert manager.calls == []
    assert not store.config_path().exists()
    assert not result["capabilities"]["local_drive_supported"]


def test_profile_revision_request_replay_and_start_stop():
    instance = pipeline()
    profile = dict(store.DEFAULT_PROFILE, remote_transport="mjpeg")
    configure = command("configure", profile=profile)
    result, code = instance.execute(configure)
    assert code == 200
    assert result["revision"] == 2
    assert instance.execute(configure) == (result, code)
    assert store.snapshot()["profile"] == profile
    same, code = instance.execute(command("configure", request_id="unchanged", revision=2, profile=profile))
    assert code == 200
    assert same["revision"] == 2
    _, code = instance.execute(command("start", request_id="start", revision=2))
    assert code == 200
    assert instance.manager.calls[-1] == ("s2_camera_preview", True)
    _, code = instance.execute(command("stop", request_id="stop", revision=2))
    assert code == 200
    assert instance.manager.calls[-1] == ("s2_camera_preview", False)


def test_stale_revision_and_reused_request_id_never_mutate():
    instance = pipeline()
    body = command("configure", profile=dict(store.DEFAULT_PROFILE, remote_transport="mjpeg"))
    result, _ = instance.execute(body)
    conflicting = command("stop", request_id=body["request_id"], revision=2)
    response, code = instance.execute(conflicting)
    assert code == 409
    assert response["error"] == "camera_pipeline_request_conflict"
    response, code = instance.execute(command("stop", request_id="stale", revision=1))
    assert code == 409
    assert response["current_revision"] == result["revision"]


@pytest.mark.parametrize(
    "change",
    [
        {"contract_version": True},
        {"expected_revision": True},
        {"expected_revision": -1},
        {"request_id": "../not-id"},
        {"action": "restart"},
        {"extra": True},
    ],
)
def test_invalid_requests_do_not_start_any_service(change):
    instance = pipeline()
    body = dict(command("start"), **change)
    _, code = instance.execute(body)
    assert code == 400
    assert instance.manager.calls == []


def test_start_profile_and_missing_engine_are_explicit_errors():
    instance = pipeline()
    assert instance.execute(command("start", profile=store.DEFAULT_PROFILE))[1] == 400
    instance.capability_fn = lambda: dict(CAPS, local_engines=[])
    response, code = instance.execute(
        command("configure", profile=dict(store.DEFAULT_PROFILE, analysis_location="local"))
    )
    assert code == 503
    assert response["error"] == "camera_pipeline_local_engine_unavailable"


def test_manual_movement_and_foreign_consumers_cannot_be_stolen():
    manager = Manager()
    manager.safety.update(moving=True, output={"lx": 0.1})
    instance = pipeline(manager)
    assert instance.execute(command("stop"))[1] == 409
    assert manager.calls == []
    manager.safety.update(moving=False, output={"lx": 0})
    manager.consumers = ["s3_follow_me_face"]
    assert instance.execute(command("stop", request_id="foreign"))[1] == 409
    assert manager.calls == []


def test_navigation_uses_existing_stop_before_switch():
    manager = Manager()
    manager.safety.update(owner="navigation", moving=True, output={"lx": 0.1})
    manager.consumers = ["s14_venom_navigation", "s2_camera_preview"]
    manager.units.add(manager.PREVIEW_UNIT)
    instance = pipeline(manager)
    body = command("configure", profile=dict(store.DEFAULT_PROFILE, remote_transport="mjpeg"))
    _, code = instance.execute(body)
    assert code == 200
    assert manager.calls == [("s14_venom_navigation", False), ("s2_camera_preview", False), ("s2_camera_preview", True)]
    assert not any(
        enabled and name in {"s14_venom_navigation", "s15_venom_perception"} for name, enabled in manager.calls
    )
    assert not manager.safety["moving"]


def test_unmanaged_camera_blocks_start_and_profile_change():
    manager = Manager()
    manager.units.add(manager.PREVIEW_UNIT)
    instance = pipeline(manager)
    result, code = instance.execute(command("start"))
    assert code == 409
    assert result["error"] == "camera_pipeline_camera_not_released"
    assert not store.config_path().exists()


def test_native_ram_source_keeps_original_bytes_and_increasing_age(monkeypatch):
    monkeypatch.setattr(pipeline_runtime, "LocalProcessor", lambda *_: pytest.fail("local model in native mode"))
    config = {"revision": 4, "profile": dict(store.DEFAULT_PROFILE, remote_transport="mjpeg")}
    producer = pipeline_runtime.CameraProducer(config)
    data, captured = b"\xff\xd8\xfffixture", time.monotonic_ns()
    producer.encoded(data, captured, (320, 240))
    first = producer.frames.get()
    second = producer.frames.get()
    assert first[0] == data
    assert first[1]["sha256"] == hashlib.sha256(data).hexdigest()
    assert first[1]["frame_id"] == producer.session + "-1"
    assert second[1]["frame_age_ms"] >= first[1]["frame_age_ms"]
    assert first[1]["captured_monotonic_ns"] == captured
    assert first[1]["image_transform"] == {"rotation": 0, "flip_h": False, "flip_v": False}
    assert not store.runtime_path().parent.joinpath("snapshots").exists()


def test_ipc_latest_only_and_stop_invalidates_cache():
    frames = pipeline_ipc.LatestFrames()
    server = pipeline_ipc.FrameServer(frames)
    server.start()
    try:
        for sequence in (1, 2):
            frames.publish(
                b"jpeg" + bytes([sequence]),
                {
                    "frame_id": "fixture-" + str(sequence),
                    "captured_monotonic_ns": time.monotonic_ns(),
                },
            )
        data, metadata = pipeline_ipc.read_frame()
        assert data == b"jpeg\x02"
        assert metadata["frame_id"] == "fixture-2"
        assert pipeline_ipc.read_frame(after="fixture-2", timeout_ms=1) is None
        assert pipeline_ipc.read_frame(metadata_only=True)[0] == b""
        frames.close()
        with pytest.raises(OSError, match="source_closed"):
            pipeline_ipc.read_frame()
    finally:
        server.close()
    assert not (store.runtime_path() / "latest.sock").exists()


def test_native_restart_changes_session_and_epoch():
    config = {"revision": 1, "profile": dict(store.DEFAULT_PROFILE, remote_transport="mjpeg")}
    first = pipeline_runtime.CameraProducer(config)
    second = pipeline_runtime.CameraProducer(config)
    assert second.session != first.session
    assert second.epoch == first.epoch + 1


def test_local_canny_is_raw_stage_and_never_returns_motion_permission():
    image = np.zeros((40, 60, 3), np.uint8)
    image[:, 30:] = 255
    before = image.copy()
    processed, detections = pipeline_local.LocalProcessor("canny").process(image)
    assert np.count_nonzero(processed) > 0
    assert detections == []
    assert np.array_equal(before, image)
    assert processed.shape == image.shape


def test_canonical_rotation_and_flips_match_legacy():
    image = np.array([[1, 2], [3, 4]], dtype=np.uint8)
    output = pipeline_local.canonical(image, {"rotation": 90, "flip_h": True, "flip_v": False})
    assert output.tolist() == [[1, 3], [2, 4]]


def test_missing_ssd_never_falls_back_to_no_model(monkeypatch, tmp_path):
    monkeypatch.setenv("SSD_MODEL_DIR", str(tmp_path / "missing"))
    with pytest.raises(RuntimeError, match="ssd_model_unavailable"):
        pipeline_local.LocalProcessor("ssd")


def test_media_endpoints_are_passive_and_use_same_source_header(monkeypatch):
    calls = []
    data = b"\xff\xd8\xfffixture"
    metadata = {"frame_id": "test-1", "sha256": hashlib.sha256(data).hexdigest(), "frame_age_ms": 20}
    monkeypatch.setattr(camera_pipeline_api, "read_frame", lambda **kwargs: calls.append(kwargs) or (data, metadata))
    app = Flask(__name__)
    camera_pipeline_api.register(app)
    client = app.test_client()
    response = client.get("/api/resource/camera/frame")
    assert response.data == data
    assert json.loads(response.headers["X-Rider-Source"]) == metadata
    assert response.headers["Cache-Control"] == "no-store"
    response = client.get("/api/resource/camera/stream.mjpg", buffered=False)
    part = next(response.response)
    response.close()
    assert data in part
    assert b"X-Rider-Source:" in part
    assert b"Content-Length:" in part
    assert calls == [{"view": "raw", "timeout_ms": 0}, {"view": "raw", "timeout_ms": 250}]


def test_media_failure_has_no_file_fallback_or_camera_start(monkeypatch):
    monkeypatch.setattr(camera_pipeline_api, "read_frame", lambda **_: (_ for _ in ()).throw(OSError("stopped")))
    app = Flask(__name__)
    camera_pipeline_api.register(app)
    client = app.test_client()
    assert client.get("/api/resource/camera/frame").status_code == 503
    assert client.get("/api/resource/camera/stream.mjpg").status_code == 503
    assert client.get("/api/resource/camera/frame?view=bad").status_code == 400


def test_legacy_camera_status_is_active_and_read_only_without_pretending_ram():
    manager = Manager()
    manager.consumers = ["s2_camera_preview"]
    manager.units.update({manager.PREVIEW_UNIT, "frame-distributor.service"})
    response = pipeline(manager).status()
    assert response["state"] == "active"
    assert response["compatibility_mode"] == "legacy"
    assert response["active_profile"] == store.DEFAULT_PROFILE
    assert response["latest_frame"] is None
    assert response["camera_session"] is None
    assert response["effective_stages"]["capture"]
    assert response["effective_stages"]["snapshot_write"]
    assert response["effective_stages"]["frame_distributor"]
    assert not response["effective_stages"]["ram_delivery"]
    assert not response["effective_stages"]["hardware_mjpeg"]
    assert manager.calls == []
    assert not store.config_path().exists()


@pytest.mark.parametrize("goal", ["s2_camera_preview", "s15_venom_perception", "s14_venom_navigation"])
def test_configure_keeps_only_passive_camera_after_release_with_new_producer(goal):
    manager = Manager()
    manager.consumers = [goal]
    manager.units.update({manager.PREVIEW_UNIT, "frame-distributor.service"})
    profile = dict(store.DEFAULT_PROFILE, remote_transport="mjpeg")
    original = manager.set_feature
    transitions = []

    def set_feature(name, enabled):
        if enabled:
            # The profile changes only after old units have released the source.
            assert name == "s2_camera_preview"
            assert manager.units == set()
            assert store.snapshot()["profile"] == profile
        else:
            assert not store.config_path().exists()
        result = original(name, enabled)
        transitions.append((name, enabled))
        if enabled:
            producer = pipeline_runtime.CameraProducer(store.snapshot())
            producer.encoded(b"\xff\xd8\xffsource", time.monotonic_ns(), (320, 240))
            pipeline_runtime.write_status(producer.status)
        return result

    manager.set_feature = set_feature
    response, code = pipeline(manager).execute(command("configure", profile=profile))
    assert code == 200
    assert response["state"] == "active"
    assert response["active_profile"] == profile
    assert response["compatibility_mode"] is None
    assert response["effective_stages"]["hardware_mjpeg"]
    assert not response["effective_stages"]["frame_distributor"]
    assert transitions == [(goal, False), ("s2_camera_preview", True)]
    assert manager.consumers == ["s2_camera_preview"]
    assert not any(
        enabled and name in {"s14_venom_navigation", "s15_venom_perception"} for name, enabled in transitions
    )


def test_explicit_same_profile_configure_upgrades_legacy_without_inventing_revision():
    manager = Manager()
    manager.consumers = ["s2_camera_preview"]
    manager.units.update({manager.PREVIEW_UNIT, "frame-distributor.service"})
    response, code = pipeline(manager).execute(command("configure", profile=dict(store.DEFAULT_PROFILE)))
    assert code == 200
    assert response["revision"] == 1
    assert store.enabled()
    assert store.snapshot()["profile"] == store.DEFAULT_PROFILE
    assert manager.calls == [("s2_camera_preview", False), ("s2_camera_preview", True)]
