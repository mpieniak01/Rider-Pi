"""Real RAM-frame decoding and legacy consumer regressions; hardware is absent."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import time
from types import ModuleType, SimpleNamespace

import cv2
import numpy as np
import pytest

from apps.camera import pipeline_ipc
from common.frame_stream import FrameStreamClient
from services import camera_pipeline as domain, camera_pipeline_store as store


@pytest.fixture(autouse=True)
def paths(monkeypatch, tmp_path):
    monkeypatch.setenv("RIDER_CAMERA_PIPELINE_CONFIG", str(tmp_path / "camera.json"))
    monkeypatch.setenv("RIDER_CAMERA_PIPELINE_RUNTIME", str(tmp_path / "runtime"))
    store.write(
        {"contract_version": 1, "revision": 1, "profile": dict(store.DEFAULT_PROFILE, remote_transport="mjpeg")}
    )


def source(*, sequence=1, age_ms=0, revision=1):
    return {
        "contract_version": 1,
        "camera_session": "camera",
        "sequence": sequence,
        "transport_epoch": 1,
        "pipeline_revision": revision,
        "frame_id": "camera-" + str(sequence),
        "captured_monotonic_ns": time.monotonic_ns() - int(age_ms * 1_000_000),
        "encoded_width": 30,
        "encoded_height": 20,
        "image_transform": {"rotation": 90, "flip_h": False, "flip_v": False},
    }


def test_explicit_local_reader_decodes_one_live_native_frame_with_canonical_rotation():
    frames = pipeline_ipc.LatestFrames()
    server = pipeline_ipc.FrameServer(frames)
    server.start()
    client = FrameStreamClient("tcp://127.0.0.1:5562", "camera.frame.raw", return_last=True)
    try:
        image = np.zeros((20, 30, 3), dtype=np.uint8)
        image[:10, :, :] = (20, 60, 230)
        ok, encoded = cv2.imencode(".jpg", image)
        assert ok
        data = encoded.tobytes()
        frames.publish(data, source())
        actual = client.recv(0)
        expected = cv2.rotate(cv2.imdecode(encoded, cv2.IMREAD_COLOR), cv2.ROTATE_90_CLOCKWISE)
        assert np.array_equal(actual, expected)
        assert actual.shape == (30, 20, 3)
        assert client.metadata["frame_id"] == "camera-1"
        assert client.metadata["timestamp_source"] == "capture"
        assert client.metadata["observed_at"] <= time.time()
        assert client.metadata["sha256"] == hashlib.sha256(data).hexdigest()
        frames.close()
        assert client.recv(0) is None
        assert client.last_frame is None
    finally:
        client.close()
        server.close()


@pytest.mark.parametrize("age_ms,revision", [(900, 1), (-900, 1), (0, 2)])
def test_ram_reader_rejects_stale_future_or_foreign_revision(age_ms, revision):
    frames = pipeline_ipc.LatestFrames()
    server = pipeline_ipc.FrameServer(frames)
    server.start()
    client = FrameStreamClient("tcp://127.0.0.1:5562", "camera.frame.raw", return_last=True)
    try:
        ok, encoded = cv2.imencode(".jpg", np.zeros((20, 30, 3), dtype=np.uint8))
        assert ok
        frames.publish(encoded.tobytes(), source(age_ms=age_ms, revision=revision))
        assert client.recv(0) is None
        assert client.last_frame is None
        assert client.metadata == {}
    finally:
        client.close()
        server.close()


def test_s7_profile_conflict_prevents_all_service_starts(tmp_path):
    from common.service_catalog import DEFAULT_REGISTRY, task_availability, unit_availability
    from services.core.features import FeatureManager, NullPublisher

    calls = []
    manager = FeatureManager(
        runner=lambda unit, action: calls.append((unit, action)) or {"ok": True},
        status_fn=lambda unit: {"unit": unit, "active": "inactive", "load": "loaded", "pid": 0},
        state_path=tmp_path / "goals.json",
        publisher=NullPublisher(),
        dependency_check=lambda *_: [],
    )
    result = manager.set_feature("s7_obstacle_module", True, options={"provider": "local"})
    assert not result["ok"]
    assert result["error"] == "camera_pipeline_profile_conflict"
    assert calls == []
    assert not unit_availability("rider-obstacle.service")["start_available"]
    store.write(
        {"contract_version": 1, "revision": 2, "profile": dict(store.DEFAULT_PROFILE, analysis_location="local")}
    )
    assert task_availability(DEFAULT_REGISTRY["s7_obstacle_module"], {"provider": "local"})["start_available"]
    assert not task_availability(DEFAULT_REGISTRY["s7_obstacle_module"], {"provider": "pc"})["start_available"]


def test_tracker_never_reads_abandoned_file_or_republishes_cached_stale_pose(monkeypatch):
    monkeypatch.setitem(sys.modules, "mediapipe", ModuleType("mediapipe"))
    from apps.vision import tracker_mediapipe as tracker

    metadata = dict(source(age_ms=50), sha256="a" * 64)
    frame = np.zeros((20, 30, 3), dtype=np.uint8)
    events, processed = [], []
    sample_queue = [
        (frame, metadata),
        (frame, metadata),
        (frame, dict(source(sequence=2, age_ms=900), sha256="b" * 64)),
        (None, {}),
    ]
    location = SimpleNamespace(
        HasField=lambda *_: True,
        relative_bounding_box=SimpleNamespace(xmin=0.7, ymin=0.1, width=0.2, height=0.2),
    )

    class Reader:
        metadata = {}

        def recv(self, *_):
            if not sample_queue:
                raise KeyboardInterrupt()
            value, self.metadata = sample_queue.pop(0)
            return value

        def close(self):
            pass

    class Detector:
        def process(self, image):
            processed.append(image)
            return SimpleNamespace(detections=[SimpleNamespace(location_data=location)])

    detector = Detector()
    monkeypatch.setattr(
        tracker,
        "mp",
        SimpleNamespace(
            solutions=SimpleNamespace(
                face_detection=SimpleNamespace(FaceDetection=lambda **_: detector),
                hands=SimpleNamespace(Hands=lambda **_: SimpleNamespace()),
            )
        ),
    )
    monkeypatch.setattr(tracker, "FrameStreamClient", lambda *_, **__: Reader())
    monkeypatch.setattr(tracker, "TRACKER_USE_FRAME_STREAM", False)
    monkeypatch.setattr(tracker, "FOLLOW_MODE", "FACE")
    monkeypatch.setattr(tracker, "should_run_local_detectors", lambda: True)
    monkeypatch.setattr(tracker, "save_tracker_frame", lambda *_: None)
    monkeypatch.setattr(tracker, "pub", lambda topic, payload: events.append((topic, payload)))
    monkeypatch.setattr(tracker.cv2, "imread", lambda *_: pytest.fail("abandoned image fallback"))
    monkeypatch.setattr(tracker.time, "sleep", lambda *_: None)
    before = time.time()
    tracker.tracking_loop()
    assert len(processed) == 1
    assert [topic for topic, _ in events] == ["vision.tracking.offset", "tracking.pose"]
    assert all(payload["frame_id"] == "camera-1" for _, payload in events)
    assert all(payload["ts"] < before for _, payload in events)
    assert all(payload["ts"] > before - 0.2 for _, payload in events)


def test_status_capabilities_do_not_import_optional_ml_parents(monkeypatch, tmp_path):
    names = []
    model = tmp_path / "model.tflite"
    model.write_bytes(b"fixture")
    monkeypatch.setenv("TFLITE_MODEL", str(model))
    monkeypatch.setattr(domain.importlib.util, "find_spec", lambda name: names.append(name) or SimpleNamespace())
    result = domain.capabilities()
    assert "tflite" in result["local_engines"]
    assert all("." not in name for name in names)
    assert "tensorflow.lite" not in names
    assert "tflite_runtime.interpreter" not in names


def test_tracking_guard_rejects_replayed_sequence_with_a_different_last_frame():
    from apps.vision.tracking_source import TrackingSourceGuard

    guard = TrackingSourceGuard()
    assert guard.admit(source(sequence=2))
    assert not guard.admit(source(sequence=1))
    assert guard.admit(source(sequence=3))
