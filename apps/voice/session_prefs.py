# apps/voice/session_prefs.py
"""
Session preferences builder for Realtime API.

Extracted from stream_chunks.py (Issue mpieniak01/Rider-Pi#80 - PR-3 refactoring).
Provides centralized session configuration assembly from TOML/ENV:
- Modalities (text, audio)
- Language and TTS voice
- Input/output audio formats (sample_rate, channels)
- System instructions/prompts
- Turn detection (server VAD or PTT/manual)
- Temperature and token limits
- Tools and tool_choice

NO API CHANGES - pure extraction of session configuration logic.
Single source of truth for session parameters to simplify A/B testing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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


@dataclass
class SessionPreferences:
    """Session preferences for Realtime API configuration.

    Attributes:
        modalities: List of modalities (e.g., ["text", "audio"])
        voice: TTS voice name (e.g., "verse", "ash", "alloy")
        instructions: System instructions/prompt for the session
        input_sample_rate: Input audio sample rate in Hz (default: 16000)
        output_sample_rate: Output audio sample rate in Hz (default: 16000)
        server_vad: Enable server-side VAD for turn detection
        silence_duration_ms: Silence duration for turn detection (ms)
        max_turn_duration_ms: Maximum turn duration (ms)
        temperature: Optional temperature for model responses
        max_tokens: Optional max response output tokens
        tools: Optional list of tools for function calling
        tool_choice: Optional tool choice strategy
    """

    modalities: list[str]
    voice: str
    instructions: str
    input_sample_rate: int
    output_sample_rate: int
    server_vad: bool
    silence_duration_ms: int
    max_turn_duration_ms: int
    temperature: float | None = None
    max_tokens: int | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None


def build_session_preferences(
    config: dict[str, Any],
    stream_cfg: Any = None,
    capture_cfg: Any = None,
) -> SessionPreferences:
    """Build session preferences from configuration.

    Args:
        config: Main configuration dict (TOML/ENV merged)
        stream_cfg: Optional stream config object (StreamConfig from svc_stream.py)
        capture_cfg: Optional capture config object (CaptureConfig)

    Returns:
        SessionPreferences with all parameters assembled from config
    """
    # Extract nested configs
    cfg_stream = (config or {}).get("stream", {}) or {}
    cfg_chat = (config or {}).get("chat", {}) or {}
    cfg_tts = (config or {}).get("tts", {}) or {}

    # Modalities (default: text + audio)
    modalities = ["text", "audio"]

    # Voice (TTS)
    voice = cfg_tts.get("voice") or _get(stream_cfg, "voice", "verse")

    # Instructions (system prompt) - prefer stream.instructions over chat.system_prompt
    instructions = cfg_stream.get("instructions")
    if not instructions:
        instructions = _get(stream_cfg, "instructions", "")
    if not instructions:
        instructions = cfg_chat.get("system_prompt", "")

    # Input sample rate (from capture config or default)
    if capture_cfg is not None:
        input_sr = int(_get(capture_cfg, "sample_rate", 16000))
    else:
        cfg_capture = (config or {}).get("capture", {}) or {}
        input_sr = int(cfg_capture.get("sample_rate", 16000))

    # Output sample rate (hardcoded to 16000 for WM8960)
    output_sr = 16000

    # Server VAD (turn detection)
    server_vad = bool(_get(stream_cfg, "server_vad", cfg_stream.get("server_vad", True)))

    # Turn detection timing
    silence_ms = int(_get(stream_cfg, "turn_end_silence_ms", cfg_stream.get("turn_end_silence_ms", 700)))
    max_turn_ms = int(_get(stream_cfg, "max_turn_ms", cfg_stream.get("max_turn_ms", 6000)))

    # Temperature (from chat config)
    temperature = None
    try:
        temp_val = cfg_chat.get("temperature")
        if temp_val is not None:
            temperature = float(temp_val)
    except (ValueError, TypeError):
        pass

    # Max tokens (from chat config)
    max_tokens = None
    try:
        mt_val = cfg_chat.get("max_tokens")
        if mt_val is not None:
            max_tokens = int(mt_val)
    except (ValueError, TypeError):
        pass

    # Tools (function calling)
    tools = cfg_chat.get("tools")
    tool_choice = cfg_chat.get("tool_choice")

    return SessionPreferences(
        modalities=modalities,
        voice=voice,
        instructions=instructions,
        input_sample_rate=input_sr,
        output_sample_rate=output_sr,
        server_vad=server_vad,
        silence_duration_ms=silence_ms,
        max_turn_duration_ms=max_turn_ms,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
        tool_choice=tool_choice,
    )


def session_prefs_to_dict(prefs: SessionPreferences) -> dict[str, Any]:
    """Convert SessionPreferences to dict for session.update message.

    Args:
        prefs: SessionPreferences instance

    Returns:
        Dict with session configuration ready for session.update
    """
    session_dict: dict[str, Any] = {
        "modalities": prefs.modalities,
        "voice": prefs.voice,
        "instructions": prefs.instructions,
        "input_audio_format": {
            "type": "pcm16",
            "sample_rate_hz": prefs.input_sample_rate,
            "channels": 1,
        },
        "output_audio_format": {
            "type": "pcm16",
            "sample_rate_hz": prefs.output_sample_rate,
            "channels": 1,
        },
        "input_audio_transcription": {"model": "whisper-1"},
    }

    # Turn detection
    if prefs.server_vad:
        session_dict["turn_detection"] = {
            "type": "server_vad",
            "silence_duration_ms": prefs.silence_duration_ms,
            "max_turn_duration_ms": prefs.max_turn_duration_ms,
        }
    else:
        session_dict["turn_detection"] = None  # PTT/manual control

    # Optional fields
    if prefs.temperature is not None:
        session_dict["temperature"] = prefs.temperature

    if prefs.max_tokens is not None:
        session_dict["max_response_output_tokens"] = prefs.max_tokens

    if prefs.tools is not None:
        session_dict["tools"] = prefs.tools

    if prefs.tool_choice is not None:
        session_dict["tool_choice"] = prefs.tool_choice

    return session_dict
