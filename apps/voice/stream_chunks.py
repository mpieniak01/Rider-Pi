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


def _get(src: Any, key: str, default: Any) -> Any:
    """Pobierz wartość z dict lub obiektu przez atrybut; w innym wypadku zwróć default."""
    try:
        if isinstance(src, dict):
            return src.get(key, default)
        if hasattr(src, key):
            return getattr(src, key)
    except Exception:
        pass
    return default


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
            "chunk_ms": _get(self.stream_cfg, "chunk_ms", 20),
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
        """Zbuduj poprawny payload `session.update` (bez zmian funkcjonalnych).

        Zwraca JSON (str), bo wysyłka po WS oczekuje tekstu.
        """
        # Lokalne referencje i fallbacki
        stream_cfg = self.stream_cfg or {}
        chat_cfg = (config or {}).get("chat", {}) or {}
        cfg_stream = (config or {}).get("stream", {}) or {}
        cfg_tts = (config or {}).get("tts", {}) or {}
        # VAD i limity tur
        silence_ms = int(_get(stream_cfg, "turn_end_silence_ms", _get(cfg_stream, "turn_end_silence_ms", 700)))
        max_turn_ms = int(_get(stream_cfg, "max_turn_ms", _get(cfg_stream, "max_turn_ms", 6000)))

        # Głos TTS, instrukcje
        voice = cfg_tts.get("voice") or _get(stream_cfg, "voice", "verse")
        instructions = _get(stream_cfg, "instructions", "")

        # turn_detection: jeśli server_vad włączony – konfigurujemy, w przeciwnym razie None
        server_vad = bool(_get(stream_cfg, "server_vad", _get(cfg_stream, "server_vad", True)))
        turn_detection: dict[str, Any] | None
        if server_vad:
            turn_detection = {
                "type": "server_vad",
                "silence_duration_ms": silence_ms,
                "max_turn_duration_ms": max_turn_ms,
            }
        else:
            turn_detection = None

        session_update: dict[str, Any] = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "voice": voice,
                "instructions": instructions,
                "turn_detection": turn_detection,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                # Transkrypcja wejścia; pozostawiamy whisper-1 jako dotychczasowy placeholder.
                "input_audio_transcription": {"model": "whisper-1"},
            },
        }

        # temperatura (opcjonalnie z chat)
        temp = chat_cfg.get("temperature", None)
        try:
            if temp is not None:
                session_update["session"]["temperature"] = float(temp)
        except (ValueError, TypeError):
            pass

        # max_tokens (opcjonalnie z chat)
        try:
            if "max_tokens" in chat_cfg:
                session_update["session"]["max_response_output_tokens"] = int(chat_cfg["max_tokens"])
        except (ValueError, TypeError):
            pass

        # tools / tool_choice (opcjonalnie)
        tools = chat_cfg.get("tools")
        if tools is not None:
            session_update["session"]["tools"] = tools

        tool_choice = chat_cfg.get("tool_choice")
        if tool_choice is not None:
            session_update["session"]["tool_choice"] = tool_choice

        return json.dumps(session_update)


def calculate_chunk_size(sample_rate: int, chunk_ms: int) -> int:
    """Calculate chunk size in bytes for given sample rate and duration."""
    return int(sample_rate * chunk_ms / 1000) * 2  # 16-bit samples


def decode_audio_from_message(message_data: dict[str, Any]) -> bytes | None:
    """Decode base64 audio data from WebSocket message."""
    try:
        msg_type = message_data.get("type")
        if msg_type == "response.audio.delta":
            audio_b64 = message_data.get("delta", "")
            if audio_b64:
                return base64.b64decode(audio_b64)
        elif msg_type == "response.audio":
            audio_b64 = message_data.get("audio", "")
            if audio_b64:
                return base64.b64decode(audio_b64)
        elif msg_type == "response.output_audio.delta":
            # Try top-level 'delta'
            audio_b64 = message_data.get("delta", "")
            if not audio_b64:
                # Try nested 'data' dict
                audio_b64 = (message_data.get("data") or {}).get("delta", "")
            if audio_b64:
                return base64.b64decode(audio_b64)
    except Exception:
        pass
    return None
