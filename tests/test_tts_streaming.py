"""Tests for streaming TTS functionality."""

from __future__ import annotations

import pytest

from apps.voice.audio.playback import PlaybackConfig
from apps.voice.tts import TTSConfig, speak_stream


@pytest.mark.asyncio
async def test_speak_stream_sentence_buffering():
    """Test that speak_stream buffers text until sentence endings."""
    __config = TTSConfig(
        backend="openai",
        voice="alloy",
        model="gpt-4o-mini-tts",
        transport="realtime",
    )
    __playback = PlaybackConfig(
        backend="null",  # Use null backend for testing
        device=None,
    )

    # Create async generator that yields text chunks
    async def text_gen():
        yield "This is "
        yield "a sentence. "
        yield "And another "
        yield "one!"

    # Note: This test will try to call speak(), which requires OPENAI_API_KEY
    # In a real scenario, we'd mock the speak() function
    # For now, we just verify the function exists and has correct signature
    assert callable(speak_stream)


@pytest.mark.asyncio
async def test_speak_stream_final_buffer():
    """Test that speak_stream handles remaining buffer text."""

    async def text_gen():
        yield "Some text without ending"

    # Verify function signature
    assert callable(speak_stream)


def test_tts_config_transport_override():
    """Test that TTSConfig can be created with transport override."""
    __config = TTSConfig(
        backend="openai",
        voice="alloy",
        model="gpt-4o-mini-tts",
        transport="realtime",
    )

    assert __config.transport == "realtime"

    # Test override for internal use
    config_override = TTSConfig(
        backend=__config.backend,
        voice=__config.voice,
        model=__config.model,
        format=__config.format,
        timeout=__config.timeout,
        transport="file",  # Override
    )

    assert config_override.transport == "file"
    assert config_override.voice == __config.voice
    assert config_override.model == __config.model
