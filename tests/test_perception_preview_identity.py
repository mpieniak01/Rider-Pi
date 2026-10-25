"""Processed preview identity comes from actual producer bytes, never GET time."""

import io
import json
import time
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from apps.camera import pipeline_ipc, pipeline_runtime
from services import camera_pipeline_store as store
from services.api_core import camera_pipeline_api
from services.api_server import app


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setenv("RIDER_CAMERA_PIPELINE_CONFIG", str(tmp_path / "camera.json"))
    monkeypatch.setenv("RIDER_CAMERA_PIPELINE_RUNTIME", str(tmp_path / "runtime"))
    monkeypatch.setenv("SNAP_DIR", str(tmp_path / "snapshots"))
    monkeypatch.setenv("PREVIEW_ROT", "0")
    monkeypatch.setenv("PREVIEW_FLIP_H", "0")
    monkeypatch.setenv("PREVIEW_FLIP_V", "0")
    monkeypatch.setattr(
        pipeline_runtime,
        "LocalProcessor",
        lambda engine: SimpleNamespace(engine=engine, process=lambda frame: (np.full_like(frame, 120), [])),
    )
    profile = dict(store.DEFAULT_PROFILE, analysis_location="local", local_engine="ssd")
    store.write({"contract_version": 1, "revision": 4, "profile": profile})
    producer = pipeline_runtime.CameraProducer(store.snapshot())
    server = pipeline_ipc.FrameServer(producer.frames)
    server.start()
    producer.frames.preview_until = time.monotonic() + 10
    producer.array(np.indices((48, 64, 3)).sum(axis=0).astype(np.uint8), time.monotonic_ns() - 100_000_000)
    try:
        yield app.test_client(), producer
    finally:
        server.close()


def test_processed_body_has_actual_processor_and_capture_identity(source):
    client, producer = source
    response = client.get("/camera/proc")
    assert response.status_code == 200
    metadata = json.loads(response.headers["X-Rider-Source-Json"])
    assert metadata["local_engine"] == "ssd"
    assert metadata["model_id"] == "local-ssd"
    assert metadata["analysis_location"] == "local"
    assert metadata["pipeline_revision"] == 4
    assert metadata["camera_session"] == producer.session
    assert metadata["transport_epoch"] == producer.epoch
    assert metadata["captured_monotonic_ns"] == producer.frames.frames["proc"][1]["captured_monotonic_ns"]
    assert metadata["frame_age_ms"] >= 100
    assert response.headers["X-Rider-Local-Engine"] == "ssd"
    assert response.headers["X-Rider-Local-Model-Id"] == "local-ssd"
    assert response.data == producer.frames.frames["proc"][0]
    with Image.open(io.BytesIO(response.data)) as image:
        assert image.size == (64, 48)


def test_raw_capture_does_not_pretend_to_be_local_inference(source):
    client, _producer = source
    response = client.get("/camera/raw")
    assert response.status_code == 200
    metadata = json.loads(response.headers["X-Rider-Source-Json"])
    assert 'model_id' not in metadata
    assert 'local_engine' not in metadata
    assert "X-Rider-Local-Model-Id" not in response.headers


def test_new_config_rejects_old_server_image_and_never_uses_fresh_file_fallback(source, monkeypatch, tmp_path):
    client, producer = source
    old = producer.frames.frames["proc"][1]
    store.write(
        {
            "contract_version": 1,
            "revision": 5,
            "profile": dict(store.DEFAULT_PROFILE, analysis_location="local", local_engine="canny"),
        }
    )
    fake = tmp_path / "fresh-but-wrong.jpg"
    fake.write_bytes(producer.frames.frames["proc"][0])
    monkeypatch.setenv("PROC_PATH", str(fake))
    response = client.get("/camera/proc")
    assert response.status_code == 503
    assert response.headers["X-Rider-Stale"] == "true"
    assert response.get_json()["error"] == "camera_pipeline_frame_unavailable"
    assert "X-Rider-Local-Model-Id" not in response.headers
    assert old['local_engine'] == 'ssd'
    assert old['pipeline_revision'] == 4


@pytest.mark.parametrize(
    "patch",
    [
        {"model_id": "local-canny"},
        {"local_engine": "canny"},
        {"analysis_location": "venom"},
        {"pipeline_revision": True},
    ],
)
def test_mismatched_model_source_is_not_relabelled_by_current_profile(source, patch):
    client, producer = source
    data, metadata = producer.frames.frames["proc"]
    producer.frames.publish(data, dict(metadata, **patch), view="proc")
    assert client.get("/api/resource/camera/frame?view=proc").status_code == 503


def test_stopping_source_clears_processed_frames(source):
    _client, producer = source
    assert producer.frames.get(view="proc") is not None
    producer.frames.close()
    assert producer.frames.get(view="proc") is None
    assert producer.frames.frames == {}
