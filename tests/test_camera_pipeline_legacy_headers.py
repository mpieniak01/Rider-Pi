"""Full application legacy image aliases translate RAM provenance, not image bytes."""

from __future__ import annotations

import hashlib
import json
import time

import cv2
import numpy as np
import pytest

from apps.camera import pipeline_ipc, pipeline_runtime
from services import camera_pipeline_store as store
from services.api_core import frames
from services.api_server import app


@pytest.fixture(params=["snapshots", "mjpeg"])
def source(monkeypatch, tmp_path, request):
    monkeypatch.setenv("RIDER_CAMERA_PIPELINE_CONFIG", str(tmp_path / "camera.json"))
    monkeypatch.setenv("RIDER_CAMERA_PIPELINE_RUNTIME", str(tmp_path / "runtime"))
    monkeypatch.setenv("PREVIEW_ROT", "90")
    monkeypatch.setenv("SNAP_DIR", str(tmp_path / "snapshots"))
    monkeypatch.setenv("PREVIEW_FLIP_H", "0")
    monkeypatch.setenv("PREVIEW_FLIP_V", "0")
    profile = dict(store.DEFAULT_PROFILE, remote_transport=request.param)
    store.write({"contract_version": 1, "revision": 4, "profile": profile})
    monkeypatch.setattr(frames, "resolve", lambda *_: pytest.fail("legacy image file fallback"))
    producer = pipeline_runtime.CameraProducer(store.snapshot())
    captured = time.monotonic_ns() - 150_000_000
    ok, raw = cv2.imencode(".jpg", np.zeros((20, 30, 3), dtype=np.uint8))
    assert ok
    ok, processed = cv2.imencode(".jpg", np.full((20, 30, 3), 200, dtype=np.uint8))
    assert ok
    if request.param == "mjpeg":
        producer.encoded(raw.tobytes(), captured, (30, 20))
    else:
        producer.array(np.zeros((20, 30, 3), dtype=np.uint8), captured)
    raw = producer.frames.frames["raw"][0]
    metadata = producer.frames.frames["raw"][1]
    producer.frames.publish(processed.tobytes(), metadata, view="proc")
    server = pipeline_ipc.FrameServer(producer.frames)
    server.start()
    try:
        yield app.test_client(), producer, {"raw": raw, "proc": processed.tobytes()}, captured
    finally:
        server.close()


@pytest.mark.parametrize(
    "route,view,stream",
    [
        ("/vision/cam", "raw", "raw"),
        ("/api/vision/cam", "raw", "raw"),
        ("/camera/raw", "raw", "raw"),
        ("/vision/edge", "proc", "proc"),
        ("/api/vision/edge", "proc", "proc"),
        ("/camera/proc", "proc", "proc"),
        ("/vision/ssd", "proc", "ssd"),
    ],
)
def test_legacy_image_alias_keeps_freshness_identity_sensor_clock_and_epoch(source, route, view, stream):
    client, producer, images, captured = source
    response = client.get(route, headers={"Accept": "application/vnd.rider.api+json;version=1"})
    assert response.status_code == 200
    assert response.mimetype == "image/jpeg"
    assert response.data == images[view]
    assert response.headers["X-Rider-Source"] == "pi-camera"
    assert response.headers["X-Rider-Contract"] == "rider.frames;version=1"
    assert response.headers["X-Rider-Stale"] == response.headers["X-Rider-Placeholder"] == "false"
    assert response.headers["X-Rider-Stream"] == stream
    assert response.headers["X-Rider-Sequence"] == "1"
    assert response.headers["X-Rider-Frame-Id"] == producer.session + "-1"
    assert response.headers["X-Rider-Camera-Session"] == producer.session
    assert response.headers["X-Rider-Transport-Epoch"] == str(producer.epoch)
    assert response.headers["X-Rider-Pipeline-Revision"] == "4"
    assert response.headers["X-Rider-Captured-Monotonic-Ns"] == str(captured)
    assert response.headers["X-Rider-Frame-Age-Source"] == "capture"
    age = float(response.headers["X-Rider-Frame-Age-Ms"])
    assert 150 <= age < 3000
    assert float(response.headers["X-Rider-Observed-At"]) < time.time() - 0.1
    assert "X-Rider-File-Observed-At" not in response.headers
    descriptor = json.loads(response.headers["X-Rider-Source-Json"])
    assert descriptor["captured_monotonic_ns"] == captured
    assert descriptor["pipeline_revision"] == 4
    assert descriptor["transport_epoch"] == producer.epoch
    assert descriptor["frame_id"] == response.headers["X-Rider-Frame-Id"]
    assert descriptor["frame_age_ms"] == age
    assert descriptor["sha256"] == hashlib.sha256(response.data).hexdigest()
    rotation = 90 if producer.config["profile"]["remote_transport"] == "mjpeg" else 0
    assert descriptor["image_transform"] == {"rotation": rotation, "flip_h": False, "flip_v": False}


def test_new_ram_endpoint_keeps_json_source_descriptor_with_original_epoch(source):
    client, producer, images, captured = source
    response = client.get("/api/resource/camera/frame")
    assert response.status_code == 200
    assert response.data == images["raw"]
    descriptor = json.loads(response.headers["X-Rider-Source"])
    assert descriptor["camera_session"] == producer.session
    assert descriptor["captured_monotonic_ns"] == captured
    assert descriptor["transport_epoch"] == producer.epoch
    assert "X-Rider-Source-Json" not in response.headers


def test_legacy_ram_unavailable_is_stale_and_cannot_fall_back_to_old_file(source):
    client, producer, _, _ = source
    producer.frames.close()
    response = client.get("/vision/cam")
    assert response.status_code == 503
    assert response.is_json
    assert response.headers["X-Rider-Stale"] == "true"
    assert response.headers["X-Rider-Source"] == "pi-camera"
    assert "X-Rider-Frame-Id" not in response.headers
    assert "X-Rider-Frame-Age-Ms" not in response.headers
