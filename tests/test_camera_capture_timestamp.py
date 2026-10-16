"""Capture-time regressions preserve sensor age through read, encoding and RAM."""

from __future__ import annotations

import json
import sys
import time
from types import SimpleNamespace

import numpy as np
import pytest

from apps.camera import pipeline_runtime, utils
from services import camera_pipeline_store as store


@pytest.fixture(autouse=True)
def paths(monkeypatch, tmp_path):
    monkeypatch.setenv("RIDER_CAMERA_PIPELINE_CONFIG", str(tmp_path / "camera.json"))
    monkeypatch.setenv("RIDER_CAMERA_PIPELINE_RUNTIME", str(tmp_path / "runtime"))
    monkeypatch.setenv("SNAP_DIR", str(tmp_path / "snapshots"))
    monkeypatch.setenv("PREVIEW_ROT", "0")
    monkeypatch.setenv("PREVIEW_FLIP_H", "0")
    monkeypatch.setenv("PREVIEW_FLIP_V", "0")
    store.write({"contract_version": 1, "revision": 1, "profile": dict(store.DEFAULT_PROFILE)})


def test_picamera_request_keeps_sensor_timestamp_after_delayed_read_and_releases(monkeypatch):
    now, released = [5_000_000_000], []
    image = np.array([[[10, 20, 30]]], dtype=np.uint8)
    captured = 4_900_000_000
    request = SimpleNamespace(
        get_metadata=lambda: {"SensorTimestamp": captured},
        make_array=lambda stream: image,
        release=lambda: released.append(True),
    )

    class Camera:
        def capture_request(self):
            now[0] += 600_000_000
            return request

    monkeypatch.setattr(utils.time, "monotonic_ns", lambda: now[0])
    reader = utils.CameraReader(Camera(), None, picamera=True, read_timed=lambda: utils._picamera_capture(Camera()))
    ok, frame, stamp = reader.capture()
    assert ok and frame.tolist() == [[[30, 20, 10]]]
    assert stamp == captured and reader.timestamp_source == "sensor" and released == [True]
    producer = pipeline_runtime.CameraProducer(store.snapshot(), clock=lambda: now[0])
    producer.array(frame, stamp)
    assert producer.frames.get()[1]["frame_age_ms"] == 700
    now[0] += 100_000_000
    assert producer.frames.get()[1]["frame_age_ms"] == 800


@pytest.mark.parametrize("captured", [None, 0, True, 6_000_000_000])
def test_picamera_invalid_timestamp_releases_request_without_renewing_it(monkeypatch, captured):
    released = []
    monkeypatch.setattr(utils.time, "monotonic_ns", lambda: 5_000_000_000)
    request = SimpleNamespace(
        get_metadata=lambda: {"SensorTimestamp": captured},
        make_array=lambda *_: pytest.fail("invalid source was decoded"),
        release=lambda: released.append(True),
    )
    with pytest.raises(RuntimeError, match="sensor_clock_invalid"):
        utils._picamera_capture(SimpleNamespace(capture_request=lambda: request))
    assert released == [True]


def test_picamera_conversion_failure_still_releases_request():
    released = []
    request = SimpleNamespace(
        get_metadata=lambda: {"SensorTimestamp": time.monotonic_ns()},
        make_array=lambda *_: (_ for _ in ()).throw(RuntimeError("buffer failed")),
        release=lambda: released.append(True),
    )
    with pytest.raises(RuntimeError, match="buffer failed"):
        utils._picamera_capture(SimpleNamespace(capture_request=lambda: request))
    assert released == [True]


def test_opencv_read_start_is_conservative_and_legacy_callable_stays_compatible(monkeypatch):
    now = [5_000_000_000]
    frame = np.zeros((20, 30, 3), dtype=np.uint8)

    def read():
        now[0] += 600_000_000
        return True, frame

    monkeypatch.setattr(utils.time, "monotonic_ns", lambda: now[0])
    reader = utils.CameraReader(SimpleNamespace(release=lambda: None), read)
    ok, actual, captured = reader.capture()
    assert ok and actual is frame and captured == 5_000_000_000
    assert reader.timestamp_source == "read_started"
    producer = pipeline_runtime.CameraProducer(store.snapshot(), clock=lambda: now[0])
    producer.array(frame, captured)
    assert producer.frames.get()[1]["frame_age_ms"] == 600
    assert reader()[1] is frame
    reader.close()
    with pytest.raises(RuntimeError, match="camera_closed"):
        reader.capture()


def test_snapshot_loop_uses_timed_capture_and_reports_driver_buffer_limitation(monkeypatch):
    import zmq

    from common import bus

    captured = time.monotonic_ns() - 600_000_000
    delivered, observations = [], []
    stop = SimpleNamespace(is_set=lambda: bool(delivered), wait=lambda *_: False)
    monkeypatch.setattr(pipeline_runtime, "threading", SimpleNamespace(Event=lambda: stop))
    publisher = SimpleNamespace(
        setsockopt=lambda *_: None,
        bind=lambda *_: None,
        close=lambda **_: None,
        send_multipart=lambda parts: delivered.append(json.loads(parts[1])),
    )
    monkeypatch.setattr(zmq, "Context", SimpleNamespace(instance=lambda: SimpleNamespace(socket=lambda *_: publisher)))
    monkeypatch.setattr(
        bus,
        "BusPub",
        lambda: SimpleNamespace(close=lambda: None, publish=lambda *args, **kwargs: observations.append(args)),
    )
    reader = utils.CameraReader(SimpleNamespace(release=lambda: None), lambda: pytest.fail("untimed capture"))
    reader.capture = lambda: (True, np.zeros((20, 30, 3), dtype=np.uint8), captured)
    monkeypatch.setattr(utils, "open_camera", lambda *_: (reader, (320, 240)))
    assert pipeline_runtime.main() == 0
    assert len(delivered) == 1 and delivered[0]["captured_monotonic_ns"] == captured
    assert delivered[0]["captured_at"] < time.time() - 0.5
    status = json.loads((store.runtime_path() / "status.json").read_text())
    assert status["capture_timestamp_source"] == "read_started"
    assert status["capture_timestamp_limitation"] == "driver_buffer_age_unknown"
    assert status["state"] == "stopped" and reader.closed


def test_picamera_initial_validation_also_releases_completed_requests(monkeypatch):
    released = []
    frame = np.zeros((20, 30, 3), dtype=np.uint8)
    request = SimpleNamespace(
        get_metadata=lambda: {"SensorTimestamp": time.monotonic_ns()},
        make_array=lambda *_: frame,
        release=lambda: released.append("request"),
    )
    camera = SimpleNamespace(
        create_preview_configuration=lambda **_: {},
        configure=lambda *_: None,
        start=lambda: None,
        capture_request=lambda: request,
        stop=lambda: released.append("stop"),
        close=lambda: released.append("close"),
    )
    monkeypatch.setitem(sys.modules, "picamera2", SimpleNamespace(Picamera2=lambda: camera))
    owner = utils._picamera_reader((30, 20))
    assert released == ["request"] and owner.timestamp_source == "sensor"
    assert owner()[0] is True and released == ["request", "request"]
    owner.close()
    assert released[-2:] == ["stop", "close"]
