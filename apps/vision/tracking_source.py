"""Capture provenance fencing for optional tracking, independent of MediaPipe."""

from __future__ import annotations

import time

from services.camera_pipeline_store import snapshot


class TrackingSourceGuard:
    def __init__(self, *, clock=time.monotonic_ns, wall=time.time):
        self.clock, self.wall = clock, wall
        self.last_frame_id = None
        self.source_key, self.sequence = None, 0

    def fresh(self, metadata):
        if not isinstance(metadata, dict):
            return False
        captured = metadata.get("captured_monotonic_ns")
        sequence = metadata.get("sequence")
        session = metadata.get("camera_session")
        return (
            type(captured) is int
            and 0 <= (self.clock() - captured) / 1_000_000_000 <= 0.5
            and metadata.get("pipeline_revision") == snapshot()["revision"]
            and type(metadata.get("transport_epoch")) is int
            and metadata["transport_epoch"] >= 0
            and type(sequence) is int
            and sequence > 0
            and isinstance(session, str)
            and 0 < len(session) <= 128
            and metadata.get("frame_id") == session + "-" + str(sequence)
        )

    def admit(self, metadata):
        if not self.fresh(metadata) or metadata["frame_id"] == self.last_frame_id:
            return False
        key = (metadata["camera_session"], metadata["transport_epoch"], metadata["pipeline_revision"])
        if key == self.source_key and metadata["sequence"] <= self.sequence:
            return False
        self.source_key, self.sequence = key, metadata["sequence"]
        self.last_frame_id = metadata["frame_id"]
        return True

    def source_time(self, metadata):
        if not self.fresh(metadata):
            return None
        return self.wall() - (self.clock() - metadata["captured_monotonic_ns"]) / 1_000_000_000
