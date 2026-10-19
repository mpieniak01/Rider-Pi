"""One ROI loop with local pixels and fake stream/BUS; no camera or socket."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from apps.vision import obstacle_roi as roi
from common.data_quality import sample_status


@pytest.mark.parametrize(
    "failure", [{"error": "camera_failed"}, {"offline": True}, {"stale": True}, {"data_ready": False}]
)
def test_explicit_stream_failure_survives_roi_and_file_fallback(monkeypatch, tmp_path, failure):
    proc = tmp_path / "processed.jpg"
    proc.write_bytes(b"previous-derived-frame")
    metadata = {"observed_at": 1000, **failure}
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    stream = SimpleNamespace(metadata=metadata, recv=lambda _: frame)
    published = []
    monkeypatch.setattr(roi, "_STOP", False)
    monkeypatch.setattr(roi, "PROC_PATH", str(proc))
    monkeypatch.setattr(roi, "USE_FRAME_STREAM", True)
    monkeypatch.setattr(roi, "OBST_ANN", False)
    monkeypatch.setattr(roi, "FrameStreamClient", lambda *a, **kw: stream)
    monkeypatch.setattr(roi, "BusSub", lambda *a: None)
    monkeypatch.setattr(roi, "should_run_local_detectors", lambda: True)
    monkeypatch.setattr(roi, "log_vision_mode_status", lambda: None)
    monkeypatch.setattr(roi.signal, "signal", lambda *a: None)
    monkeypatch.setattr(roi, "now_s", lambda: 1000)
    monkeypatch.setattr(roi, "sample_status", lambda row, **kw: sample_status(row, now=1000, **kw))
    monkeypatch.setattr(roi, "atomic_write_json", lambda *a: None)
    monkeypatch.setattr(roi, "publish", lambda topic, row: published.append((topic, row)))
    monkeypatch.setattr(roi.time, "sleep", lambda _: setattr(roi, "_STOP", True))
    assert roi.main() == 0
    row = next(row for topic, row in published if topic == "vision.obstacle")
    assert not row["data_ready"]
    assert row["stale"]
    assert row["error"]
    assert row["observed_at"] == 1000
    # A later restart/file-only consumer sees a deliberately invalidated source.
    assert proc.stat().st_mtime == 0
    assert not sample_status({"observed_at": proc.stat().st_mtime}, now=1000, max_age_s=0.5)["ready"]


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"observed_at": None, "error": "camera_capture_failed"},
        {"observed_at": float("inf")},
        {"observed_at": float("nan")},
    ],
)
def test_unknown_stream_age_is_null_in_strict_json(monkeypatch, tmp_path, metadata):
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    stream = SimpleNamespace(metadata=metadata, recv=lambda _: frame)
    _run_strict_roi_loop(monkeypatch, tmp_path, stream)
    row = json.loads((tmp_path / "obstacle.json").read_text())
    assert row["age_s"] is None
    assert row["observed_at"] is None
    assert row["data_ready"] is False
    assert row["stale"] is True
    assert row["error"] == metadata.get("error", "invalid_source_time")


def test_missing_processed_frame_age_is_null_in_strict_json(monkeypatch, tmp_path):
    monkeypatch.setattr(roi, "load_gray", lambda _: None)
    _run_strict_roi_loop(monkeypatch, tmp_path, None)
    row = json.loads((tmp_path / "obstacle.json").read_text())
    assert row["age_s"] is None
    assert row["data_ready"] is False
    assert row["stale"] is True
    assert row["error"] == "proc_not_found"


def test_known_stream_age_remains_finite_in_strict_json(monkeypatch, tmp_path):
    stream = SimpleNamespace(metadata={"observed_at": 999.75}, recv=lambda _: np.zeros((10, 10, 3), dtype=np.uint8))
    _run_strict_roi_loop(monkeypatch, tmp_path, stream)
    row = json.loads((tmp_path / "obstacle.json").read_text())
    assert row["age_s"] == 0.25
    assert row["observed_at"] == 999.75
    assert row["data_ready"] is True
    assert row["stale"] is False
    assert row["error"] is None


def _run_strict_roi_loop(monkeypatch, tmp_path, stream):
    monkeypatch.setattr(roi, "_STOP", False)
    monkeypatch.setattr(roi, "_LAST_STREAM_FRAME", None)
    monkeypatch.setattr(roi, "PROC_PATH", str(tmp_path / "missing.jpg"))
    monkeypatch.setattr(roi, "OBSTACLE_JSON", str(tmp_path / "obstacle.json"))
    monkeypatch.setattr(roi, "USE_FRAME_STREAM", stream is not None)
    monkeypatch.setattr(roi, "OBST_ANN", False)
    monkeypatch.setattr(roi, "FrameStreamClient", lambda *a, **kw: stream)
    monkeypatch.setattr(roi, "BusSub", lambda *a: None)
    monkeypatch.setattr(roi, "should_run_local_detectors", lambda: True)
    monkeypatch.setattr(roi, "log_vision_mode_status", lambda: None)
    monkeypatch.setattr(roi.signal, "signal", lambda *a: None)
    monkeypatch.setattr(roi, "now_s", lambda: 1000)
    monkeypatch.setattr(roi, "sample_status", lambda row, **kw: sample_status(row, now=1000, **kw))
    writer = roi.atomic_write_json

    def strict_write(path, payload):
        json.dumps(payload, allow_nan=False)
        writer(path, payload)

    monkeypatch.setattr(roi, "atomic_write_json", strict_write)
    monkeypatch.setattr(roi, "publish", lambda topic, row: json.dumps(row, allow_nan=False))
    monkeypatch.setattr(roi.time, "sleep", lambda _: setattr(roi, "_STOP", True))
    assert roi.main() == 0
