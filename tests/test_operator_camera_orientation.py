"""Operator camera orientation stays compatible across snapshot/native profiles."""

from __future__ import annotations

import time

import numpy as np
import pytest

from apps.camera import pipeline_runtime
from services import camera_pipeline_store as store


@pytest.fixture(autouse=True)
def camera_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("RIDER_CAMERA_PIPELINE_CONFIG", str(tmp_path / "camera.json"))
    monkeypatch.setenv("RIDER_CAMERA_PIPELINE_RUNTIME", str(tmp_path / "runtime"))
    monkeypatch.setenv("SNAP_DIR", str(tmp_path / "snapshots"))
    store.write(
        {"contract_version": 1, "revision": 1, "profile": dict(store.DEFAULT_PROFILE, remote_transport="mjpeg")}
    )


@pytest.mark.parametrize("rotation", [None, "", "0", "90", "180", "270"])
def test_pipeline_orientation_preserves_legacy_raw_default_and_overrides(monkeypatch, rotation):
    import ast
    import os
    from pathlib import Path

    import cv2

    from apps.camera.pipeline_local import canonical, image_transform

    if rotation is None:
        monkeypatch.delenv("PREVIEW_ROT", raising=False)
    else:
        monkeypatch.setenv("PREVIEW_ROT", rotation)
    monkeypatch.setenv("PREVIEW_FLIP_H", "0")
    monkeypatch.setenv("PREVIEW_FLIP_V", "0")

    # Execute only the old RAW's pure rotation contract, never its I/O/bootstrap.
    legacy_path = Path(__file__).parents[1] / "apps/camera/preview_lcd.py"
    parsed = ast.parse(legacy_path.read_text())
    nodes = [
        node
        for node in parsed.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "ROT" for target in node.targets)
        or isinstance(node, ast.FunctionDef)
        and node.name == "rotate_bgr"
    ]
    legacy = {"os": os, "cv2": cv2}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(legacy_path), "exec"), legacy)
    frame = np.arange(4 * 6 * 3, dtype=np.uint8).reshape(4, 6, 3)
    transform = image_transform()
    assert transform["rotation"] == legacy["ROT"]
    assert np.array_equal(canonical(frame, transform), legacy["rotate_bgr"](frame, legacy["ROT"]))


@pytest.mark.parametrize("rotation", [None, "", "0", "90", "180", "270"])
def test_snapshots_and_native_preserve_same_camera_orientation_once(monkeypatch, rotation):
    import cv2

    from apps.camera.pipeline_local import canonical, image_transform

    if rotation is None:
        monkeypatch.delenv("PREVIEW_ROT", raising=False)
    else:
        monkeypatch.setenv("PREVIEW_ROT", rotation)
    monkeypatch.setenv("PREVIEW_FLIP_H", "0")
    monkeypatch.setenv("PREVIEW_FLIP_V", "0")
    frame = np.empty((80, 120, 3), dtype=np.uint8)
    frame[:40, :60] = (20, 20, 220)
    frame[:40, 60:] = (20, 220, 20)
    frame[40:, :60] = (220, 20, 20)
    frame[40:, 60:] = (20, 220, 220)
    expected = canonical(frame, image_transform())

    snapshot = pipeline_runtime.CameraProducer({"revision": 1, "profile": dict(store.DEFAULT_PROFILE)})
    snapshot.array(frame, time.monotonic_ns())
    snapshot_bytes, snapshot_source = snapshot.frames.frames["raw"]
    assert snapshot_source["image_transform"] == {"rotation": 0, "flip_h": False, "flip_v": False}
    native = pipeline_runtime.CameraProducer(store.snapshot())
    ok, encoded = cv2.imencode(".jpg", frame)
    assert ok
    native.encoded(encoded.tobytes(), time.monotonic_ns(), (120, 80))
    native_bytes, native_source = native.frames.frames["raw"]
    outputs = [
        cv2.imdecode(np.frombuffer(snapshot_bytes, np.uint8), cv2.IMREAD_COLOR),
        canonical(
            cv2.imdecode(np.frombuffer(native_bytes, np.uint8), cv2.IMREAD_COLOR), native_source["image_transform"]
        ),
    ]
    for output in outputs:
        assert output.shape == expected.shape
        height, width = output.shape[:2]
        for row, column in [
            (height // 4, width // 4),
            (height // 4, 3 * width // 4),
            (3 * height // 4, width // 4),
            (3 * height // 4, 3 * width // 4),
        ]:
            assert np.max(np.abs(output[row, column].astype(int) - expected[row, column])) < 15
