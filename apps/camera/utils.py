"""Shared helpers for camera preview scripts."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

import cv2

VIDEO_DEVICE = os.getenv("VIDEO_DEVICE")


def env_flag(name: str, default: bool = False) -> bool:
    """Return boolean value of environment flag *name*."""
    return str(os.getenv(name, str(int(default)))).lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }


def _validate_picamera_capture(fn: Callable[[], Any], attempts: int = 3, delay: float = 0.1) -> None:
    """Ensure Picamera2 delivers at least one frame; raise RuntimeError otherwise."""
    last_err: Exception | None = None
    for _ in range(max(1, attempts)):
        try:
            frame = fn()
            if frame is not None:
                return
        except Exception as exc:  # pragma: no cover - defensive
            last_err = exc
        time.sleep(delay)
    raise RuntimeError(f"Picamera2 capture failed: {last_err or 'no frame'}")


def _picamera_reader(size: tuple[int, int]):
    from picamera2 import Picamera2  # type: ignore

    picam2 = Picamera2()
    try:
        config = picam2.create_preview_configuration(main={"size": size, "format": "RGB888"})
        picam2.configure(config)
        picam2.start()
        _validate_picamera_capture(picam2.capture_array)
    except Exception:
        try:
            if hasattr(picam2, "close"):
                picam2.close()
            else:
                picam2.stop()
        except Exception:  # pragma: no cover - best effort cleanup
            pass
        raise

    def read() -> tuple[bool, Any]:
        arr = picam2.capture_array()
        return True, cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

    return read


def _v4l2_reader(size: tuple[int, int]):
    device = int(VIDEO_DEVICE) if (VIDEO_DEVICE and VIDEO_DEVICE.isdigit()) else (VIDEO_DEVICE or 0)
    cap = cv2.VideoCapture(device)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])
    try:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    except Exception:
        pass

    def read() -> tuple[bool, Any]:
        return cap.read()

    return read


def open_camera(
    size: tuple[int, int] = (320, 240),
) -> tuple[Callable[[], tuple[bool, Any]], tuple[int, int]]:
    """Open Picamera2 when available, falling back to V4L2."""
    try:
        return _picamera_reader(size), size
    except Exception:
        return _v4l2_reader(size), size
