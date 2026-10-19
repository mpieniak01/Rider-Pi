"""Actual camera adapter construction owns fake backends until idempotent close."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from apps.camera import utils


def test_open_camera_picamera_owner_closes_underlying_backend(monkeypatch):
    frame = np.zeros((2, 3, 3), np.uint8)
    camera = SimpleNamespace(
        create_preview_configuration=Mock(return_value="configuration"),
        configure=Mock(),
        start=Mock(),
        stop=Mock(),
        close=Mock(),
    )
    monkeypatch.setitem(sys.modules, "picamera2", SimpleNamespace(Picamera2=lambda: camera))
    monkeypatch.setattr(utils, "_picamera_capture", lambda _camera: (True, frame, 123))
    reader, size = utils.open_camera((3, 2))
    assert isinstance(reader, utils.CameraReader)
    assert size == (3, 2)
    assert reader()[1] is frame
    reader.close()
    reader.close()
    camera.stop.assert_called_once()
    camera.close.assert_called_once()
    with pytest.raises(RuntimeError, match="camera_closed"):
        reader()


def test_open_camera_v4l2_fallback_releases_underlying_backend(monkeypatch):
    frame = np.zeros((2, 3, 3), np.uint8)
    camera = SimpleNamespace(read=Mock(return_value=(True, frame)), set=Mock(), isOpened=lambda: True, release=Mock())
    monkeypatch.setattr(utils, "_picamera_reader", Mock(side_effect=ImportError("optional backend absent")))
    monkeypatch.setattr(utils.cv2, "VideoCapture", Mock(return_value=camera))
    reader, size = utils.open_camera((3, 2))
    assert isinstance(reader, utils.CameraReader)
    assert size == (3, 2)
    assert reader()[1] is frame
    reader.close()
    reader.close()
    camera.release.assert_called_once()


def test_picamera_close_still_closes_device_when_stop_raises():
    camera = SimpleNamespace(stop=Mock(side_effect=OSError("stop failed")), close=Mock())
    reader = utils.CameraReader(camera, None, picamera=True)
    with pytest.raises(OSError, match="stop failed"):
        reader.close()
    camera.close.assert_called_once()
    assert reader.closed is True


@pytest.mark.parametrize("picamera", [True, False])
def test_hog_local_adapter_owns_actual_fake_backend(monkeypatch, picamera):
    import ast
    from pathlib import Path

    frame = np.zeros((2, 3, 3), np.uint8)
    camera = SimpleNamespace(
        create_preview_configuration=Mock(return_value="configuration"),
        configure=Mock(),
        start=Mock(),
        stop=Mock(),
        close=Mock(),
        capture_array=lambda: frame,
        set=Mock(),
        read=lambda: (True, frame),
        release=Mock(),
    )
    monkeypatch.setitem(sys.modules, "picamera2", SimpleNamespace(Picamera2=lambda: camera) if picamera else None)
    fake_cv = SimpleNamespace(
        VideoCapture=lambda _device: camera,
        CAP_PROP_FRAME_WIDTH=3,
        CAP_PROP_FRAME_HEIGHT=4,
        COLOR_RGB2BGR=1,
        cvtColor=lambda array, _code: array,
    )
    path = Path(__file__).resolve().parents[1] / "apps/vision/detector_hog.py"
    tree = ast.parse(path.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) if node.name == "open_camera")
    namespace = {"W": 3, "H": 2, "cv2": fake_cv, "CameraReader": utils.CameraReader}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    reader, size = namespace["open_camera"]((3, 2))
    assert isinstance(reader, utils.CameraReader)
    assert size == (3, 2)
    assert reader()[1] is frame
    reader.close()
    reader.close()
    if picamera:
        camera.stop.assert_called_once()
        camera.close.assert_called_once()
        camera.release.assert_not_called()
    else:
        camera.release.assert_called_once()
        camera.stop.assert_not_called()
