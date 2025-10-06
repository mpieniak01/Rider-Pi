# tests/test_session_prefs.py
"""Tests for session preferences builder (PR-3)."""

import pytest

from apps.voice.session_prefs import (
    SessionPreferences,
    build_session_preferences,
    session_prefs_to_dict,
)


def test_build_session_preferences_defaults():
    """Test building session preferences with minimal config."""
    config = {
        "stream": {},
        "chat": {},
        "tts": {},
        "capture": {},
    }

    prefs = build_session_preferences(config)

    assert prefs.modalities == ["text", "audio"]
    assert prefs.voice == "verse"
    assert prefs.instructions == ""
    assert prefs.input_sample_rate == 16000
    assert prefs.output_sample_rate == 16000
    assert prefs.server_vad is True
    assert prefs.silence_duration_ms == 700
    assert prefs.max_turn_duration_ms == 6000
    assert prefs.temperature is None
    assert prefs.max_tokens is None
    assert prefs.tools is None
    assert prefs.tool_choice is None


def test_build_session_preferences_custom_voice():
    """Test building session preferences with custom TTS voice."""
    config = {
        "stream": {},
        "chat": {},
        "tts": {"voice": "ash"},
        "capture": {},
    }

    prefs = build_session_preferences(config)
    assert prefs.voice == "ash"


def test_build_session_preferences_server_vad_disabled():
    """Test building session preferences with server VAD disabled (PTT mode)."""
    config = {
        "stream": {"server_vad": False},
        "chat": {},
        "tts": {},
        "capture": {},
    }

    prefs = build_session_preferences(config)
    assert prefs.server_vad is False


def test_build_session_preferences_custom_sample_rate():
    """Test building session preferences with custom input sample rate."""
    config = {
        "stream": {},
        "chat": {},
        "tts": {},
        "capture": {"sample_rate": 48000},
    }

    prefs = build_session_preferences(config)
    assert prefs.input_sample_rate == 48000
    assert prefs.output_sample_rate == 16000  # Always 16k for WM8960


def test_build_session_preferences_with_temperature():
    """Test building session preferences with temperature setting."""
    config = {
        "stream": {},
        "chat": {"temperature": 0.7},
        "tts": {},
        "capture": {},
    }

    prefs = build_session_preferences(config)
    assert prefs.temperature == 0.7


def test_build_session_preferences_with_max_tokens():
    """Test building session preferences with max_tokens setting."""
    config = {
        "stream": {},
        "chat": {"max_tokens": 150},
        "tts": {},
        "capture": {},
    }

    prefs = build_session_preferences(config)
    assert prefs.max_tokens == 150


def test_build_session_preferences_with_instructions():
    """Test building session preferences with custom instructions."""
    config = {
        "stream": {"instructions": "You are a helpful assistant."},
        "chat": {"system_prompt": "Default prompt"},
        "tts": {},
        "capture": {},
    }

    prefs = build_session_preferences(config)
    assert prefs.instructions == "You are a helpful assistant."


def test_build_session_preferences_with_system_prompt_fallback():
    """Test building session preferences using chat.system_prompt as fallback."""
    config = {
        "stream": {},
        "chat": {"system_prompt": "I am Rider-Pi."},
        "tts": {},
        "capture": {},
    }

    prefs = build_session_preferences(config)
    assert prefs.instructions == "I am Rider-Pi."


def test_build_session_preferences_with_tools():
    """Test building session preferences with function calling tools."""
    tools = [
        {
            "type": "function",
            "name": "get_weather",
            "description": "Get weather info",
            "parameters": {},
        }
    ]
    config = {
        "stream": {},
        "chat": {"tools": tools, "tool_choice": "auto"},
        "tts": {},
        "capture": {},
    }

    prefs = build_session_preferences(config)
    assert prefs.tools == tools
    assert prefs.tool_choice == "auto"


def test_build_session_preferences_custom_turn_detection():
    """Test building session preferences with custom turn detection timing."""
    config = {
        "stream": {
            "turn_end_silence_ms": 1000,
            "max_turn_ms": 8000,
        },
        "chat": {},
        "tts": {},
        "capture": {},
    }

    prefs = build_session_preferences(config)
    assert prefs.silence_duration_ms == 1000
    assert prefs.max_turn_duration_ms == 8000


def test_session_prefs_to_dict_minimal():
    """Test converting minimal session preferences to dict."""
    prefs = SessionPreferences(
        modalities=["text", "audio"],
        voice="verse",
        instructions="",
        input_sample_rate=16000,
        output_sample_rate=16000,
        server_vad=True,
        silence_duration_ms=700,
        max_turn_duration_ms=6000,
    )

    result = session_prefs_to_dict(prefs)

    assert result["modalities"] == ["text", "audio"]
    assert result["voice"] == "verse"
    assert result["instructions"] == ""
    assert result["input_audio_format"]["type"] == "pcm16"
    assert result["input_audio_format"]["sample_rate_hz"] == 16000
    assert result["input_audio_format"]["channels"] == 1
    assert result["output_audio_format"]["type"] == "pcm16"
    assert result["output_audio_format"]["sample_rate_hz"] == 16000
    assert result["output_audio_format"]["channels"] == 1
    assert result["input_audio_transcription"]["model"] == "whisper-1"
    assert result["turn_detection"]["type"] == "server_vad"
    assert result["turn_detection"]["silence_duration_ms"] == 700
    assert result["turn_detection"]["max_turn_duration_ms"] == 6000


def test_session_prefs_to_dict_ptt_mode():
    """Test converting session preferences with server_vad=False (PTT mode)."""
    prefs = SessionPreferences(
        modalities=["text", "audio"],
        voice="verse",
        instructions="",
        input_sample_rate=16000,
        output_sample_rate=16000,
        server_vad=False,
        silence_duration_ms=700,
        max_turn_duration_ms=6000,
    )

    result = session_prefs_to_dict(prefs)
    assert result["turn_detection"] is None


def test_session_prefs_to_dict_with_optional_fields():
    """Test converting session preferences with all optional fields."""
    tools = [{"type": "function", "name": "test"}]
    prefs = SessionPreferences(
        modalities=["text", "audio"],
        voice="ash",
        instructions="Test instructions",
        input_sample_rate=16000,
        output_sample_rate=16000,
        server_vad=True,
        silence_duration_ms=700,
        max_turn_duration_ms=6000,
        temperature=0.8,
        max_tokens=200,
        tools=tools,
        tool_choice="auto",
    )

    result = session_prefs_to_dict(prefs)

    assert result["temperature"] == 0.8
    assert result["max_response_output_tokens"] == 200
    assert result["tools"] == tools
    assert result["tool_choice"] == "auto"


def test_build_session_preferences_invalid_temperature():
    """Test that invalid temperature is ignored."""
    config = {
        "stream": {},
        "chat": {"temperature": "invalid"},
        "tts": {},
        "capture": {},
    }

    prefs = build_session_preferences(config)
    assert prefs.temperature is None


def test_build_session_preferences_invalid_max_tokens():
    """Test that invalid max_tokens is ignored."""
    config = {
        "stream": {},
        "chat": {"max_tokens": "invalid"},
        "tts": {},
        "capture": {},
    }

    prefs = build_session_preferences(config)
    assert prefs.max_tokens is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
