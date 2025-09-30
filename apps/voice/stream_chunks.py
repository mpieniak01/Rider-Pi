# apps/voice/stream_chunks.py
"""Audio chunk processing for streaming voice service.

Extracted from svc_stream.py to keep files under 600 lines.
Handles 20ms buffer management, downmix to 16kHz, audioop utilities, 
and base64 pack/unpack for WebSocket transmission.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from . import voice_logging
from .capture import CaptureConfig
from .svc_audio import ensure_mono_16k


class AudioChunkProcessor:
    """Handles audio chunk processing for streaming."""

    def __init__(self, capture_cfg_obj: CaptureConfig, stream_cfg: Any, logger: voice_logging.VoiceLogger):
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

        # Normalize to mono 16kHz before transmission (bez resamplingu)
        normalized_audio = ensure_mono_16k(audio_data, self.capture_cfg_obj)

        # Convert to base64 for JSON transmission
        audio_b64 = base64.b64encode(normalized_audio).decode("utf-8")
        message = {"type": "input_audio_buffer.append", "audio": audio_b64}

        # Telemetria
        telemetry = {
            "bytes_in": len(audio_data),
            "bytes_out": len(normalized_audio),
            "ch_in": int(self.capture_cfg_obj.channels or 1),
            "ch_out": 1,
            "sr": int(self.capture_cfg_obj.sample_rate or 16000),
            "chunk_ms": self.stream_cfg.chunk_ms,
        }

        return json.dumps(message), telemetry

    def create_commit_message(self) -> str:
        """Create audio buffer commit message."""
        return json.dumps({"type": "input_audio_buffer.commit"})

    def create_response_message(self, config: dict[str, Any]) -> str:
        """Create response request message."""
        tts_cfg = config.get("tts", {}) or {}
        voice = tts_cfg.get("voice") or "verse"
        response_msg = {
            "type": "response.create",
            "response": {
                "conversation": "default",
                "instructions": "Odpowiadaj krótko i po polsku.",
                "modalities": ["text", "audio"],
                "audio": {"voice": voice, "format": "pcm16"},
            },
        }
        return json.dumps(response_msg)

    def create_session_update_message(self, config: dict[str, Any]) -> str:
        """Create session configuration update message."""
        asr_cfg = config.get("asr", {})
        chat_cfg = config.get("chat", {})
        tts_cfg = config.get("tts", {}) or {}

        voice = tts_cfg.get("voice") or "verse"
        session_update = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "voice": voice,
                "instructions": "Odpowiadaj krótko i po polsku.",
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": self.stream_cfg.turn_end_silence_ms,
                },
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {"model": "whisper-1"},
            },
        }

        # Add temperature from chat config if available
        if "temperature" in chat_cfg:
            try:
                session_update["session"]["temperature"] = float(chat_cfg["temperature"])
            except (ValueError, TypeError):
                pass

        # Add max_tokens from chat config if available
        if "max_tokens" in chat_cfg:
            try:
                session_update["session"]["max_response_output_tokens"] = int(chat_cfg["max_tokens"])
            except (ValueError, TypeError):
                pass

        return json.dumps(session_update)


def calculate_chunk_size(sample_rate: int, chunk_ms: int) -> int:
    """Calculate chunk size in bytes for given sample rate and duration."""
    return int(sample_rate * chunk_ms / 1000) * 2  # 16-bit samples


def decode_audio_from_message(message_data: dict[str, Any]) -> bytes | None:
    """Decode base64 audio data from WebSocket message."""
    try:
        if message_data.get("type") == "response.audio.delta":
            audio_b64 = message_data.get("delta", "")
            if audio_b64:
                return base64.b64decode(audio_b64)
        elif message_data.get("type") == "response.audio":
            audio_b64 = message_data.get("audio", "")
            if audio_b64:
                return base64.b64decode(audio_b64)
    except Exception:
        pass
    return None