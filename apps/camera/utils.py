"""Shared helpers for camera preview scripts."""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import cv2


def env_flag(name: str, default: bool = False) -> bool:
    """Return boolean value of environment flag *name*."""
    return str(os.getenv(name, str(int(default)))).lower() in {"1", "true", "yes", "y", "on"}


def open_camera(
    size: tuple[int, int] = (320, 240),
) -> tuple[Callable[[], tuple[bool, Any]], tuple[int, int]]:
    """Open Picamera2 when available, falling back to V4L2."""
    try:
        from picamera2 import Picamera2  # type: ignore

        picam2 = Picamera2()
        config = picam2.create_preview_configuration(main={"size": size, "format": "RGB888"})
        picam2.configure(config)
        picam2.start()

        def read() -> tuple[bool, Any]:
            arr = picam2.capture_array()
            return True, cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

        return read, size
    except Exception:
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])
        try:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        except Exception:
            pass

        def read() -> tuple[bool, Any]:
            return cap.read()

        return read, size
