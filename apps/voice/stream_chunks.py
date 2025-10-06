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
    build_session_update,
    decode_audio_from_message as rt_decode_audio,
)
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
            "chunk_ms": _get(self.stream_cfg, "chunk_ms", 20),
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

        # turn_detection: włączony server VAD albo brak (PTT)
        server_vad = bool(_get(stream_cfg, "server_vad", _get(cfg_stream, "server_vad", True)))

        # Format wejścia/wyjścia
        in_sr = int(_get(self.capture_cfg_obj, "sample_rate", 16000))

        # temperatura (opcjonalnie z chat)
        temp = chat_cfg.get("temperature", None)
        try:
            if temp is not None:
                temp = float(temp)
        except (ValueError, TypeError):
            temp = None

        # Build base message using rt_protocol
        message = build_session_update(
            voice=voice,
            instructions=instructions,
            input_sample_rate=in_sr,
            output_sample_rate=16000,
            server_vad=server_vad,
            silence_duration_ms=silence_ms,
            max_turn_duration_ms=max_turn_ms,
            temperature=temp,
        )

        # Parse to add additional fields not in base builder
        session_update = json.loads(message)

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
    return int(sample_rate * chunk_ms / 1000) * 2  # 16-bit mono (2 bajty na próbkę)


def decode_audio_from_message(message_data: dict[str, Any]) -> bytes | None:
    """Decode base64 audio data from WebSocket message (RT API variants).

    Delegates to rt_protocol.decode_audio_from_message for compatibility.
    """
    return rt_decode_audio(message_data)
