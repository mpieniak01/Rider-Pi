# apps/voice/stream_chunks.py
"""
Audio chunk processing for streaming voice service.

Extracted from svc_stream.py to keep files under 600 lines.
Handles 20ms buffer management, downmix/resample to 16kHz, audioop utilities,
and base64 pack/unpack for WebSocket transmission.

NOTE: Message builders now delegated to rt_protocol.py (PR-1 refactoring).
"""

from __future__ import annotations

import json
from typing import Any

# ⬇️ Uwaga: celowo NIE importujemy voice_logging, żeby uniknąć pętli importów
# from . import voice_logging
from .capture import CaptureConfig
from .rt_protocol import (
    build_audio_append,
    build_audio_commit,
    build_response_create,
    decode_audio_from_message as rt_decode_audio,
)
from .session_prefs import build_session_preferences, session_prefs_to_dict
from .svc_audio import ensure_mono_16k


class AudioChunkProcessor:
    """Handles audio chunk processing for streaming."""

    # logger typujemy jako Any, żeby nie ściągać voice_logging przy imporcie modułu
    def __init__(self, capture_cfg_obj: CaptureConfig, stream_cfg: Any, logger: Any):
        self.capture_cfg_obj = capture_cfg_obj
        self.stream_cfg = stream_cfg
        self.logger = logger

    def process_and_encode_chunk(self, audio_data: bytes) -> tuple[str, dict[str, Any]] | None:
        """Process audio chunk and encode for WebSocket transmission.

        Returns:
            Tuple of (JSON message string, telemetry dict) or None if no data
        """
        if not audio_data:
            return None

        # Normalizacja do mono/16 kHz (ensure_mono_16k resampluje/konwertuje jeśli trzeba)
        normalized_audio = ensure_mono_16k(audio_data, self.capture_cfg_obj)

        # Use rt_protocol builder
        message = build_audio_append(normalized_audio)

        telemetry = {
            "bytes_in": len(audio_data),
            "bytes_out": len(normalized_audio),
            "ch_in": int(self.capture_cfg_obj.channels or 1),
            "ch_out": 1,
            "sr": int(self.capture_cfg_obj.sample_rate or 16000),
            "chunk_ms": getattr(self.stream_cfg, "chunk_ms", 20),
        }

        return message, telemetry

    def create_commit_message(self) -> str:
        """Create audio buffer commit message."""
        return build_audio_commit()

    def create_response_message(self, config: dict[str, Any]) -> str:
        """Create response request message (modalities + voice).

        Uwaga: format audio konfigurujemy w session.update (nie tutaj).
        """
        tts_cfg = (config or {}).get("tts", {}) or {}
        voice = tts_cfg.get("voice") or "verse"

        return build_response_create(voice=voice, instructions="Odpowiadaj krótko i po polsku.")

    def create_session_update_message(self, config: dict[str, Any]) -> str:
        """Zbuduj poprawny payload `session.update` i zwróć JSON (str)."""
        # Build session preferences from config
        prefs = build_session_preferences(
            config=config,
            stream_cfg=self.stream_cfg,
            capture_cfg=self.capture_cfg_obj,
        )

        # Convert to session dict
        session_dict = session_prefs_to_dict(prefs)

        # Wrap in session.update message
        session_update = {
            "type": "session.update",
            "session": session_dict,
        }

        return json.dumps(session_update)


def calculate_chunk_size(sample_rate: int, chunk_ms: int) -> int:
    """Calculate chunk size in bytes for given sample rate and duration."""
    return int(sample_rate * chunk_ms / 1000) * 2  # 16-bit mono (2 bajty na próbkę)


def decode_audio_from_message(message_data: dict[str, Any]) -> bytes | None:
    """Decode base64 audio data from WebSocket message (RT API variants).

    Delegates to rt_protocol.decode_audio_from_message for compatibility.
    """
    return rt_decode_audio(message_data)
