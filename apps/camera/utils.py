"""One closable camera owner shared by RAW, EDGE, SSD and preview clients."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

import cv2

VIDEO_DEVICE = os.getenv("VIDEO_DEVICE")


def env_flag(name: str, default: bool = False) -> bool:
    return str(os.getenv(name, str(int(default)))).lower() in {"1", "true", "yes", "y", "on"}


class CameraReleaseError(RuntimeError):
    pass


class CameraReader:
    def __init__(self, camera, read, *, picamera=False):
        self.camera, self.read_frame, self.picamera = camera, read, picamera
        self.closed = False

    def __call__(self):
        if self.closed:
            raise RuntimeError("camera_closed")
        return self.read_frame()

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.picamera:
            try:
                self.camera.stop()
            finally:
                self.camera.close()
        else:
            self.camera.release()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _validate_picamera_capture(fn: Callable[[], Any], attempts: int = 3, delay: float = 0.1) -> None:
    last_err = None
    for _ in range(max(1, attempts)):
        try:
            if fn() is not None:
                return
        except Exception as exc:
            last_err = exc
        time.sleep(delay)
    raise RuntimeError(f"Picamera2 capture failed: {last_err or 'no frame'}")


def _picamera_reader(size):
    from picamera2 import Picamera2

    camera = Picamera2()
    owner = CameraReader(camera, lambda: (True, cv2.cvtColor(camera.capture_array(), cv2.COLOR_RGB2BGR)), picamera=True)
    try:
        config = camera.create_preview_configuration(main={"size": size, "format": "RGB888"})
        camera.configure(config)
        camera.start()
        _validate_picamera_capture(camera.capture_array)
        return owner
    except BaseException:
        try:
            owner.close()
        except Exception as error:
            raise CameraReleaseError("camera_release_failed") from error
        raise


def _v4l2_reader(size):
    device = int(VIDEO_DEVICE) if VIDEO_DEVICE and VIDEO_DEVICE.isdigit() else VIDEO_DEVICE or 0
    camera = cv2.VideoCapture(device)
    owner = CameraReader(camera, camera.read)
    try:
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])
        if hasattr(camera, "isOpened") and not camera.isOpened():
            raise RuntimeError("camera_unavailable")
        try:
            camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        except Exception:
            pass
        return owner
    except BaseException:
        owner.close()
        raise


def open_camera(size=(320, 240)):
    """The callable also owns stop/close; every consumer must close it."""
    try:
        return _picamera_reader(size), size
    except CameraReleaseError:
        raise
    except Exception:
        return _v4l2_reader(size), size
