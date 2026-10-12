from __future__ import annotations

import importlib
import json

from common.data_quality import finite_number

cv2 = None
np = None

try:
    import zmq
except Exception:  # pragma: no cover - pyzmq only available on device
    zmq = None  # type: ignore[assignment]


class FrameStreamClient:
    """Utility for subscribing to frame-distributor streams via ZMQ."""

    def __init__(
        self,
        addr: str,
        topic: str,
        *,
        return_last: bool = False,
        copy_frame: bool = False,
        latest: bool = False,
        max_pending: int = 2,
        encoded: bool = False,
    ) -> None:
        if zmq is None:
            raise RuntimeError("pyzmq unavailable")
        if latest and (type(max_pending) is not int or not 1 <= max_pending <= 16):
            raise ValueError("max_pending must be 1..16")
        global cv2, np
        if not encoded and (cv2 is None or np is None):
            try:
                cv2 = importlib.import_module("cv2")
                np = importlib.import_module("numpy")
            except ImportError as exc:
                raise RuntimeError("opencv unavailable") from exc

        self._return_last = return_last
        self._copy_frame = copy_frame
        self._last_frame: np.ndarray | None = None
        self._last_metadata = {}
        self._latest = latest
        self._encoded = encoded
        self._topic = topic.encode("utf-8")

        self._ctx = zmq.Context.instance()
        self._sock = self._ctx.socket(zmq.SUB)
        self._sock.setsockopt(zmq.LINGER, 0)
        if latest:
            self._sock.setsockopt(zmq.RCVHWM, max_pending)
        self._sock.connect(addr)
        self._sock.setsockopt(zmq.SUBSCRIBE, self._topic)

        self._poller = zmq.Poller()
        self._poller.register(self._sock, zmq.POLLIN)

    def close(self) -> None:
        try:
            self._poller.unregister(self._sock)
        except Exception:
            # Ignore errors if socket already unregistered or poller is closed
            pass
        try:
            self._sock.close()
        except Exception:
            # Ignore errors during socket cleanup
            pass

    def _fallback(self) -> np.ndarray | None:
        if not self._return_last or self._last_frame is None:
            return None
        return self._copy(self._last_frame)

    def _copy(self, frame):
        # Encoded bytes are immutable and do not need another 2 MiB allocation.
        return frame.copy() if self._copy_frame and not isinstance(frame, bytes) else frame

    def _candidate(self, parts):
        if (
            len(parts) != 3
            or parts[0] != getattr(self, '_topic', parts[0])
            or len(parts[1]) > 8192
            or not isinstance(parts[2], bytes)
            or not 0 < len(parts[2]) <= 2 * 1024 * 1024
        ):
            return None
        try:
            metadata = json.loads(parts[1])
        except (ValueError, TypeError, UnicodeDecodeError):
            return None
        if not isinstance(metadata, dict):
            return None
        if getattr(self, '_encoded', False):
            data = parts[2]
            if not (
                data.startswith(b'\xff\xd8\xff')
                or data.startswith(b'\x89PNG\r\n\x1a\n')
                or data.startswith(b'BM')
                or data.startswith(b'RIFF')
                and data[8:12] == b'WEBP'
            ):
                return None
        observed = metadata.get("captured_at", metadata.get("observed_at", metadata.get("mtime")))
        return parts[2], dict(metadata, observed_at=observed if finite_number(observed) else None)

    def recv(self, timeout_ms: int) -> np.ndarray | None:
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
        candidate = self._candidate(parts)
        if getattr(self, '_latest', False):
            # Drain encoded messages first; decode just the latest useful frame.
            for _ in range(16):
                try:
                    parts = self._sock.recv_multipart(zmq.NOBLOCK)
                except zmq.Again:
                    break
                # Malformed later messages cannot replace a valid candidate.
                latest = self._candidate(parts)
                if latest is not None:
                    candidate = latest
        if candidate is None:
            return self._fallback()
        data, metadata = candidate
        if getattr(self, '_encoded', False):
            frame = data
        else:
            try:
                arr = np.frombuffer(data, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            except Exception:
                frame = None
        if frame is None:
            return self._fallback()

        # Commit metadata only together with a valid frame. Publication/poll
        # times never refresh the age of cached or malformed image messages.
        self._last_metadata = metadata
        if self._return_last:
            # Store an immutable reference if the caller expects to reuse cached frames.
            self._last_frame = frame if isinstance(frame, bytes) else frame.copy()

        return self._copy(frame)

    @property
    def metadata(self) -> dict:
        return dict(self._last_metadata)

    @property
    def last_frame(self) -> np.ndarray | None:
        if self._last_frame is None:
            return None
        return self._copy(self._last_frame)
