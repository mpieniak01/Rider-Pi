"""Vision boundaries use AST-only detector entrypoints and synthetic observations."""

from __future__ import annotations

import ast
import json
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from common import observations

ROOT = Path(__file__).resolve().parents[1]


def definitions(relative, names, namespace):
    tree = ast.parse((ROOT / relative).read_text())
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(functions) == len(names)
    exec(compile(ast.Module(body=functions, type_ignores=[]), relative, "exec"), namespace)
    return namespace


@pytest.mark.parametrize(
    "active,failed_read,expected_detections", [(True, False, 1), (True, True, 0), (False, False, 0)]
)
def test_hog_main_processes_valid_local_frames_and_closes_all_fakes(active, failed_read, expected_detections):
    frame = np.zeros((20, 30, 3), np.uint8)
    detector = SimpleNamespace(
        setSVMDetector=Mock(),
        detectMultiScale=Mock(return_value=([(1, 2, 3, 4)], [0.9])),
    )
    subscriber = SimpleNamespace(close=Mock())
    publisher = SimpleNamespace(publish=Mock())
    heartbeat = SimpleNamespace(tick=Mock())
    read_count = [0]

    class Camera:
        close = Mock()

        def __call__(self):
            read_count[0] += 1
            if read_count[0] > 1:
                raise KeyboardInterrupt()
            return not failed_read, frame

    camera = Camera()
    clock = [0.0]

    def now():
        clock[0] += 0.001
        return clock[0]

    def sleep(_seconds):
        if not active or failed_read:
            raise KeyboardInterrupt()

    open_camera = Mock(return_value=(camera, (30, 20)))
    fake_cv = SimpleNamespace(
        HOGDescriptor=lambda: detector,
        HOGDescriptor_getDefaultPeopleDetector=lambda: "fake-model",
        rectangle=Mock(),
        putText=Mock(),
        FONT_HERSHEY_SIMPLEX=0,
        LINE_AA=0,
    )
    namespace = definitions(
        "apps/vision/detector_hog.py",
        {"main", "_initial_hog_capture", "_process_hog_frame", "_close_hog_resources"},
        {
            "log_vision_mode_status": Mock(),
            "BusSub": lambda _topics: subscriber,
            "TOPIC_SYSTEM_AI_MODE_CHANGED": "mode",
            "TOPIC_PROVIDER_VISION_STATE": "provider",
            "should_run_local_detectors": lambda: active,
            "open_camera": open_camera,
            "cv2": fake_cv,
            "_poll_hog_mode": lambda _sub, state, reader, hog: (state, reader, hog, False),
            "os": SimpleNamespace(makedirs=Mock()),
            "SNAP_DIR": "fake-snapshots",
            "time": SimpleNamespace(time=now, sleep=sleep),
            "HB": heartbeat,
            "PUB": publisher,
            "save_jpeg_bgr": Mock(),
            "PROC_FN": "fake-proc.jpg",
            "MAX_FPS": 10,
        },
    )
    with pytest.raises(KeyboardInterrupt):
        namespace["main"]()
    assert detector.detectMultiScale.call_count == expected_detections
    assert publisher.publish.call_count == expected_detections
    assert heartbeat.tick.call_count == 1 + expected_detections
    subscriber.close.assert_called_once()
    if active:
        camera.close.assert_called_once()
        open_camera.assert_called_once()
    else:
        open_camera.assert_not_called()
    if expected_detections:
        args, kwargs = publisher.publish.call_args
        assert args[0] == "vision.person"
        assert args[1]["bbox"] == [1, 2, 3, 4]
        assert kwargs == {"add_ts": True}
        detector.setSVMDetector.assert_called_once_with("fake-model")


@pytest.mark.parametrize(
    "edge,last,dark,blur,expected",
    [
        (0.05, False, False, False, True),
        (0.2, True, False, False, False),
        (0.1, True, False, False, True),
        (0.1, False, False, False, False),
        (0.9, False, True, False, True),
        (0.9, False, False, True, True),
    ],
)
def test_obstacle_hysteresis_and_occlusion_thresholds(edge, last, dark, blur, expected):
    namespace = definitions(
        "apps/vision/obstacle_roi.py",
        {"_obstacle_presence_confidence", "clamp"},
        {"EDGE_T_LOW": 0.05, "EDGE_T_HIGH": 0.2, "CONF_GAIN": 1.0},
    )
    present, confidence = namespace["_obstacle_presence_confidence"](edge, dark, blur, last)
    assert present is expected
    assert 0 <= confidence <= 1
    if dark or blur:
        assert confidence >= 0.5


def test_obstacle_invalid_or_reordered_frame_clears_history():
    quality = {"ready": True}
    namespace = definitions(
        "apps/vision/obstacle_roi.py",
        {"_update_obstacle_history"},
        {
            "sample_status": lambda *_args, **_kwargs: quality,
            "SNAP_MAX_AGE_S": 1,
        },
    )
    history, times = deque([0.1, 0.2], maxlen=3), deque([10, 11], maxlen=3)
    namespace["_update_obstacle_history"]({}, 9, 0.4, history, times)
    assert list(history) == [0.4]
    assert list(times) == [9]
    quality["ready"] = False
    namespace["_update_obstacle_history"]({}, 12, 0.8, history, times)
    assert list(history) == []
    assert list(times) == []


@pytest.mark.parametrize("topic,expected", [("motion.sensor.raw", None), ("devices.xgo", 99)])
def test_telemetry_keeps_missing_measurement_time_distinct_from_reception(topic, expected):
    assert observations._sensor_time("roll", {}, {"ts": 99}, {}, topic) == expected


def test_telemetry_timestamp_precedence_retains_explicit_invalid_sensor_time():
    data = {"imu_observed_at": 90, "observed_at": 91, "ts": 92}
    assert observations._sensor_time("roll", {"observed_at": None}, data, {"roll": 89}, "devices.xgo") is None
    assert observations._sensor_time("roll", {}, data, {"roll": 89}, "devices.xgo") == 89
    assert observations._sensor_time("roll", {}, data, {}, "devices.xgo") == 90


@pytest.mark.parametrize(
    "quality,error",
    [
        ({"offline": True}, "measurement_offline"),
        ({"simulated": True}, "measurement_simulated"),
        ({"stale": True}, "measurement_not_ready"),
        ({"ready": False}, "measurement_not_ready"),
    ],
)
def test_measurement_quality_flags_never_refresh_sample_readiness(quality, error):
    row = observations.measurement("roll", 1, 10, quality=quality, now=11)
    assert row["observed_at"] == 10
    assert row["age_s"] == 1
    assert row["ready"] is False
    assert row["error"] == error


def test_measurement_unit_error_precedes_invalid_value_and_quality_error():
    row = observations.measurement("battery", 500, 10, unit="percent", quality={"offline": True}, now=11)
    assert row["value"] is None
    assert row["error"] == "measurement_unit_unknown"


def test_tflite_dispatcher_reads_string_transport_without_dead_branch():
    receiver = SimpleNamespace(recv_string=Mock(return_value='vision.person {"score":0.8}'))
    namespace = definitions("apps/vision/detector_tflite.py", {"sub_recv"}, {"SUB": receiver, "json": json})
    assert namespace["sub_recv"]() == ("vision.person", {"score": 0.8})
    receiver.recv_string.assert_called_once()
