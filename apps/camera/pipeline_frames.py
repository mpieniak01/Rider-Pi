"""Decoded optional local consumers share the producer's bounded RAM source."""

from __future__ import annotations

import time

from apps.camera.pipeline_ipc import read_frame
from apps.camera.pipeline_local import canonical
from services.camera_pipeline_store import snapshot


class PipelineFrameClient:
    def __init__(self, *, return_last=False, copy_frame=False):
        import cv2
        import numpy as np

        self.cv, self.np = cv2, np
        self.return_last, self.copy_frame = return_last, copy_frame
        self._frame, self._metadata, self.closed = None, {}, False

    def _clear(self):
        self._frame, self._metadata = None, {}

    def _valid(self, metadata):
        stamp = metadata.get("captured_monotonic_ns")
        sequence = metadata.get("sequence")
        session = metadata.get("camera_session")
        return (
            metadata.get("pipeline_revision") == snapshot()["revision"]
            and type(stamp) is int
            and 0 <= (time.monotonic_ns() - stamp) / 1_000_000_000 <= 0.5
            and isinstance(session, str)
            and 0 < len(session) <= 128
            and type(sequence) is int
            and sequence > 0
            and metadata.get("frame_id") == session + "-" + str(sequence)
            and type(metadata.get("transport_epoch")) is int
            and metadata["transport_epoch"] >= 0
        )

    def recv(self, timeout_ms):
        if self.closed:
            return None
        try:
            item = read_frame(after=self._metadata.get("frame_id"), timeout_ms=timeout_ms)
            if item is None:
                if self.return_last and self._frame is not None and self._valid(self._metadata):
                    return self._frame.copy() if self.copy_frame else self._frame
                self._clear()
                return None
            data, metadata = item
            if not self._valid(metadata):
                self._clear()
                return None
            image = self.cv.imdecode(self.np.frombuffer(data, dtype=self.np.uint8), self.cv.IMREAD_COLOR)
            if image is None or image.shape[:2] != (metadata["encoded_height"], metadata["encoded_width"]):
                self._clear()
                return None
            image = canonical(image, metadata["image_transform"])
            captured_at = time.time() - (time.monotonic_ns() - metadata["captured_monotonic_ns"]) / 1_000_000_000
            self._metadata = dict(
                metadata,
                observed_at=captured_at,
                captured_at=captured_at,
                timestamp_source="capture",
            )
            self._frame = image
            return image.copy() if self.copy_frame else image
        except (OSError, ValueError, KeyError, TypeError):
            # Disconnect/profile mismatch invalidates cached pixels as well.
            self._clear()
            return None

    @property
    def metadata(self):
        return dict(self._metadata)

    @property
    def last_frame(self):
        return self._frame.copy() if self._frame is not None and self.copy_frame else self._frame

    def close(self):
        self.closed = True
        self._clear()
