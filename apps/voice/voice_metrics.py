# apps/voice/voice_metrics.py
"""Voice service metrics tracking.

Extracted from svc_stream.py (Issue mpieniak01/Rider-Pi#58 PR-2 - audio TX/RX + metrics).
Provides counters and timers for: bytes added/committed, RTT, drops, reconnects.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class VoiceMetrics:
    """Metrics for voice streaming service."""

    # Audio transmission metrics
    audio_bytes_in: int = 0  # Raw bytes captured
    audio_bytes_out: int = 0  # Bytes sent to WebSocket (base64-encoded)
    audio_chunks_sent: int = 0
    audio_chunks_dropped: int = 0

    # Audio reception metrics
    tts_bytes_received: int = 0
    tts_chunks_received: int = 0

    # Response timing metrics
    last_commit_ts: float | None = None
    last_response_ts: float | None = None
    response_rtt_ms: float | None = None  # Round-trip time for last response

    # Connection metrics
    reconnects: int = 0
    connection_start_ts: float | None = None
    connection_duration_s: float = 0.0

    # Internal state
    _start_time: float = field(default_factory=time.time)

    def on_audio_chunk(self, bytes_in: int, bytes_out: int) -> None:
        """Record audio chunk sent to WebSocket."""
        self.audio_bytes_in += bytes_in
        self.audio_bytes_out += bytes_out
        self.audio_chunks_sent += 1

    def on_audio_drop(self, count: int = 1) -> None:
        """Record dropped audio chunks."""
        self.audio_chunks_dropped += count

    def on_tts_chunk(self, bytes_received: int) -> None:
        """Record TTS chunk received."""
        self.tts_bytes_received += bytes_received
        self.tts_chunks_received += 1

    def on_commit(self) -> None:
        """Record audio commit timestamp."""
        self.last_commit_ts = time.time()

    def on_response(self) -> None:
        """Record response received and calculate RTT."""
        self.last_response_ts = time.time()
        if self.last_commit_ts is not None:
            self.response_rtt_ms = (self.last_response_ts - self.last_commit_ts) * 1000.0

    def on_connect(self) -> None:
        """Record connection start."""
        self.connection_start_ts = time.time()

    def on_disconnect(self) -> None:
        """Record connection end and update duration."""
        if self.connection_start_ts is not None:
            self.connection_duration_s += time.time() - self.connection_start_ts
            self.connection_start_ts = None

    def on_reconnect(self) -> None:
        """Increment reconnect counter."""
        self.reconnects += 1

    def to_dict(self) -> dict[str, Any]:
        """Export metrics as dictionary."""
        return {
            "audio_bytes_in": self.audio_bytes_in,
            "audio_bytes_out": self.audio_bytes_out,
            "audio_chunks_sent": self.audio_chunks_sent,
            "audio_chunks_dropped": self.audio_chunks_dropped,
            "tts_bytes_received": self.tts_bytes_received,
            "tts_chunks_received": self.tts_chunks_received,
            "response_rtt_ms": self.response_rtt_ms,
            "reconnects": self.reconnects,
            "connection_duration_s": self.connection_duration_s,
            "uptime_s": time.time() - self._start_time,
        }

    def reset(self) -> None:
        """Reset all counters (keep connection state)."""
        self.audio_bytes_in = 0
        self.audio_bytes_out = 0
        self.audio_chunks_sent = 0
        self.audio_chunks_dropped = 0
        self.tts_bytes_received = 0
        self.tts_chunks_received = 0
        self.last_commit_ts = None
        self.last_response_ts = None
        self.response_rtt_ms = None
