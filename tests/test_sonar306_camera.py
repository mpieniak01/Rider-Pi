"""Camera packet contracts use images and AST-extracted preview helpers only."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from apps.camera import pipeline_local, pipeline_runtime, tflite_detector
from apps.camera.frame_distributor import FrameDistributor

ROOT = Path(__file__).resolve().parents[1]


def functions_only(relative, names, namespace):
    source = ast.parse((ROOT / relative).read_text())
    definitions = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(definitions) == len(names)
    exec(compile(ast.Module(body=definitions, type_ignores=[]), relative, "exec"), namespace)
    return namespace


@pytest.fixture
def raw_detections():
    values = np.zeros((1, 1, 4, 7), dtype=np.float32)
    values[0, 0] = [
        [0, 1, 0.8, -0.1, -0.2, 0.8, 0.9],
        [0, 1, 0.7, 0.8, 0.8, 0.2, 0.2],
        [0, 0, 0.9, 0.1, 0.1, 0.5, 0.5],
        [0, 1, 0.2, 0.1, 0.1, 0.5, 0.5],
    ]
    return values


@pytest.mark.parametrize(
    "relative,function,labels",
    [
        ("apps/camera/preview_lcd.py", "_preview_ssd_detections", "CLASSES_SSD"),
        ("apps/camera/preview_lcd_ssd.py", "_ssd_fresh_detections", "CLASSES"),
    ],
)
def test_ssd_preview_clips_boxes_filters_classes_and_drops_degenerate_boxes(relative, function, labels, raw_detections):
    namespace = functions_only(
        relative, {function}, {"cv2": cv2, labels: ["background", "person"], "VISION_MIN_SCORE": 0.5}
    )
    detector = SimpleNamespace(setInput=Mock(), forward=lambda: raw_detections)
    frame = np.zeros((20, 30, 3), np.uint8)
    args = (
        (frame, detector, {"person"}) if function == "_preview_ssd_detections" else (frame, detector, 0.5, {"person"})
    )
    found = namespace[function](*args)
    assert len(found) == 1
    assert found[0][0] == "person"
    assert found[0][1] == pytest.approx(0.8)
    assert found[0][2] == (0, 0, 24, 17)
    detector.setInput.assert_called_once()


def test_local_ssd_preserves_threshold_and_draws_only_filtered_detections(raw_detections):
    processor = object.__new__(pipeline_local.LocalProcessor)
    processor.cv = cv2
    processor.engine = "ssd"
    processor.threshold = 0.5
    processor.classes = {"aeroplane"}
    processor.detector = SimpleNamespace(setInput=Mock(), forward=lambda: raw_detections)
    frame = np.zeros((20, 30, 3), np.uint8)
    out, detections = processor.process(frame)
    assert len(detections) == 1
    assert detections[0][0] == "aeroplane"
    assert np.any(out)
    assert not np.any(frame)


def test_snapshot_cadence_keeps_independent_raw_and_ui_frames():
    calls = []
    namespace = functions_only(
        "apps/camera/preview_lcd.py",
        {"_save_preview_feeds"},
        {
            "SAVE_LAST_EVERY": 3,
            "SAVE_RAW_EVERY": 2,
            "save_last_frame": lambda _frame, **kw: calls.append(("last", kw["frame_id"], kw["captured_at"])),
            "save_raw_snapshot": lambda _frame, **kw: calls.append(("raw", kw["frame_id"], kw["captured_at"])),
        },
    )
    for frame in range(4):
        namespace["_save_preview_feeds"](object(), frame, 1.5, "session")
    assert calls == [
        ("last", "session-0", 1.5),
        ("raw", "session-0", 1.5),
        ("raw", "session-2", 1.5),
        ("last", "session-3", 1.5),
    ]


def test_ssd_latch_is_drawn_but_not_republished_as_a_new_hit():
    draw, publish = Mock(), Mock()
    latched = [("person", 0.8, (1, 1, 3, 3))]
    infer = Mock(side_effect=AssertionError("inference cadence skipped"))
    namespace = functions_only(
        "apps/camera/preview_lcd_ssd.py",
        {"_ssd_preview_frame"},
        {
            "_ssd_fresh_detections": infer,
            "latch_dets": lambda fresh: latched,
            "_draw_ssd_detections": draw,
            "_publish_ssd_detections": publish,
        },
    )
    frame = np.zeros((20, 30, 3), np.uint8)
    out, fresh = namespace["_ssd_preview_frame"](frame, object(), 1, 2, 0.5, {"person"})
    assert fresh == []
    assert np.array_equal(out, frame)
    assert out is not frame
    assert draw.call_args.args[1] is latched
    publish.assert_called_once_with([])


def test_tflite_output_selection_keeps_strongest_scores_and_first_class_tensor():
    boxes = np.zeros((1, 10, 4), np.float32)
    classes = np.zeros((1, 10), np.int32)
    first_scores = np.full((1, 10), 0.2, np.float32)
    stronger_scores = np.full((1, 10), 0.8, np.float32)
    count = np.array([[2]], np.int32)
    parsed = tflite_detector._detection_outputs([boxes, classes, first_scores, stronger_scores, count])
    assert all(actual is expected for actual, expected in zip(parsed, [boxes, classes, stronger_scores, count]))


def test_tflite_inference_preserves_threshold_and_degenerate_box_rejection():
    boxes = np.zeros((1, 10, 4), np.float32)
    boxes[0, :2] = [[0, 0, 1, 1], [0.8, 0.8, 0.2, 0.2]]
    outputs = [boxes, np.zeros((1, 10), np.int32), np.full((1, 10), 0.8, np.float32), np.array([[2]], np.int32)]
    detector = object.__new__(tflite_detector.TFLiteEffDet)
    detector.in_h = detector.in_w = 8
    detector.input_details = [{"index": 1}]
    detector.output_details = [{"index": index} for index in range(4)]
    detector.interp = SimpleNamespace(set_tensor=Mock(), invoke=Mock(), get_tensor=lambda index: outputs[index])
    assert detector.infer(np.zeros((20, 30, 3), np.uint8), 0.5) == [("person", pytest.approx(0.8), (0, 0, 30, 20))]


@pytest.mark.parametrize("raw_topic", [True, False])
def test_distributor_heartbeat_selects_raw_only_for_raw_topic(monkeypatch, raw_topic):
    from apps.camera import frame_distributor

    monkeypatch.setattr(
        frame_distributor, "FRAME_STREAM_TOPIC", b"camera.frame.raw" if raw_topic else b"camera.frame.proc"
    )
    distributor = object.__new__(FrameDistributor)
    distributor.frame_path = "old"
    distributor.frame_mode = "old"
    distributor._apply_heartbeat({"raw_frame_path": "raw", "last_frame_path": "proc", "mode": "ssd"})
    assert (distributor.frame_path, distributor.frame_mode) == (("raw", "raw") if raw_topic else ("proc", "ssd"))
    distributor._apply_heartbeat({"mode": "", "last_frame_path": None})
    assert distributor.frame_path == ("raw" if raw_topic else "proc")


def test_native_watchdog_checks_stall_before_configuration_and_heartbeat(monkeypatch):
    producer = SimpleNamespace(status={"latest_frame": {"captured_monotonic_ns": 1}}, heartbeat=Mock())
    stop = SimpleNamespace(wait=lambda _delay: False)
    monkeypatch.setattr(pipeline_runtime, "time", SimpleNamespace(monotonic_ns=lambda: 3_000_000_002))
    monkeypatch.setattr(pipeline_runtime, "snapshot", Mock(side_effect=AssertionError("stall checked first")))
    with pytest.raises(RuntimeError, match="capture_stalled"):
        pipeline_runtime._run_native_capture({}, stop, producer)
    producer.heartbeat.assert_not_called()
