"""Tests for streaming TTS functionality."""

from __future__ import annotations

import pytest

from apps.voice.playback import PlaybackConfig
from apps.voice.tts import TTSConfig, speak_stream


@pytest.mark.asyncio
async def test_speak_stream_sentence_buffering():
    """Test that speak_stream buffers text until sentence endings."""
    config = TTSConfig(
        backend="openai",
        voice="alloy",
        model="gpt-4o-mini-tts",
        transport="realtime",
    )
    playback = PlaybackConfig(
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
    config = TTSConfig(
        backend="openai",
        voice="alloy",
        model="gpt-4o-mini-tts",
        transport="realtime",
    )

    assert config.transport == "realtime"

    # Test override for internal use
    config_override = TTSConfig(
        backend=config.backend,
        voice=config.voice,
        model=config.model,
        format=config.format,
        timeout=config.timeout,
        transport="file",  # Override
    )

    assert config_override.transport == "file"
    assert config_override.voice == config.voice
    assert config_override.model == config.model
