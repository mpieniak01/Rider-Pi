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
