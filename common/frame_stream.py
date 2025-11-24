from __future__ import annotations

from typing import Optional

try:
    import cv2
    import numpy as np
except Exception:  # pragma: no cover - OpenCV only available on device
    cv2 = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]

try:
    import zmq
except Exception:  # pragma: no cover - pyzmq only available on device
    zmq = None  # type: ignore[assignment]


class FrameStreamClient:
    """Utility for subscribing to frame-distributor streams via ZMQ."""

    def __init__(self, addr: str, topic: str, *, return_last: bool = False, copy_frame: bool = False) -> None:
        if zmq is None:
            raise RuntimeError("pyzmq unavailable")
        if cv2 is None or np is None:
            raise RuntimeError("opencv unavailable")

        self._return_last = return_last
        self._copy_frame = copy_frame
        self._last_frame: Optional[np.ndarray] = None

        self._ctx = zmq.Context.instance()
        self._sock = self._ctx.socket(zmq.SUB)
        self._sock.setsockopt(zmq.LINGER, 0)
        self._sock.connect(addr)
        self._sock.setsockopt(zmq.SUBSCRIBE, topic.encode("utf-8"))

        self._poller = zmq.Poller()
        self._poller.register(self._sock, zmq.POLLIN)

    def close(self) -> None:
        try:
            self._poller.unregister(self._sock)
        except Exception:
            pass
        try:
            self._sock.close()
        except Exception:
            pass

    def _fallback(self) -> Optional[np.ndarray]:
        if not self._return_last or self._last_frame is None:
            return None
        return self._last_frame.copy() if self._copy_frame else self._last_frame

    def recv(self, timeout_ms: int) -> Optional[np.ndarray]:
        """Receive next frame from the stream, optionally returning cached frame on timeouts."""

        try:
            events = dict(self._poller.poll(timeout_ms))
        except Exception:
            return self._fallback()
        if self._sock not in events:
            return self._fallback()
        try:
            parts = self._sock.recv_multipart(zmq.NOBLOCK)
        except zmq.Again:
            return self._fallback()
        if len(parts) < 3:
            return self._fallback()

        data = parts[2]
        try:
            arr = np.frombuffer(data, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        except Exception:
            frame = None

        if frame is None:
            return self._fallback()

        if self._return_last:
            # Store an immutable reference if the caller expects to reuse cached frames.
            self._last_frame = frame.copy()

        return frame.copy() if self._copy_frame else frame

    @property
    def last_frame(self) -> Optional[np.ndarray]:
        if self._last_frame is None:
            return None
        return self._last_frame.copy() if self._copy_frame else self._last_frame
