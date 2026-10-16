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
    def __init__(self, camera, read, *, picamera=False, read_timed=None):
        self.camera, self.read_frame, self.picamera = camera, read, picamera
        self.read_timed = read_timed
        self.timestamp_source = "sensor" if read_timed is not None else "read_started"
        self.closed = False

    def __call__(self):
        return self.capture()[:2]

    def capture(self):
        """Return the original capture time; a blocking read must not renew age."""
        if self.closed:
            raise RuntimeError("camera_closed")
        if self.read_timed is not None:
            return self.read_timed()
        # OpenCV does not expose a trustworthy capture timestamp. This excludes
        # read latency from freshness but cannot account for older driver buffers.
        started = time.monotonic_ns()
        ok, frame = self.read_frame()
        return ok, frame, started

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


def _picamera_capture(camera):
    completed = camera.capture_request()
    try:
        captured = completed.get_metadata().get("SensorTimestamp")
        if type(captured) is not int or not 0 < captured <= time.monotonic_ns():
            raise RuntimeError("camera_pipeline_sensor_clock_invalid")
        # Conversion copies out of the request-owned buffer before release.
        frame = cv2.cvtColor(completed.make_array("main"), cv2.COLOR_RGB2BGR)
        return True, frame, captured
    finally:
        completed.release()


def _picamera_reader(size):
    from picamera2 import Picamera2

    camera = Picamera2()
    owner = CameraReader(camera, None, picamera=True, read_timed=lambda: _picamera_capture(camera))
    try:
        config = camera.create_preview_configuration(main={"size": size, "format": "RGB888"})
        camera.configure(config)
        camera.start()
        _validate_picamera_capture(lambda: owner.capture()[1])
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
