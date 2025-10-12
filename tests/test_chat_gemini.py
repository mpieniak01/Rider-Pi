"""Tests for Google Gemini chat integration."""

from __future__ import annotations

import os

import pytest

if os.getenv("RUN_STRICT_GEMINI_TESTS") != "1":
    pytest.skip(
        "Skipping strict Gemini/OpenAI key/SDK tests by default (set RUN_STRICT_GEMINI_TESTS=1 to run).",
        allow_module_level=True,
    )


import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.voice.chat import ChatConfig, ChatError, ChatSession


def test_chat_session_ask_gemini_requires_api_key():
    """Test that Gemini backend requires GOOGLE_API_KEY."""
    config = ChatConfig(
        backend="google",
        model="gemini-pro",
        system_prompt="Test prompt",
        transport="file",
    )
    session = ChatSession(config)

    # Remove GOOGLE_API_KEY if it exists
    old_key = os.environ.pop("GOOGLE_API_KEY", None)
    try:
        with pytest.raises(ChatError, match="GOOGLE_API_KEY is not set"):
            session.ask("Hello")
    finally:
        if old_key:
            os.environ["GOOGLE_API_KEY"] = old_key


def test_chat_session_ask_gemini_requires_model():
    """Test that Gemini backend requires model configuration."""
    config = ChatConfig(
        backend="google",
        model="",
        system_prompt="Test prompt",
        transport="file",
    )
    session = ChatSession(config)

    with pytest.raises(ChatError, match="Google model not configured"):
        session.ask("Hello")


def test_chat_session_ask_gemini_blocks_rest_in_realtime_mode():
    """Test that Gemini REST is blocked when transport=realtime."""
    config = ChatConfig(
        backend="google",
        model="gemini-pro",
        system_prompt="Test prompt",
        transport="realtime",
    )
    session = ChatSession(config)

    with pytest.raises(ChatError, match="Chat REST disabled when transport=realtime"):
        session.ask("Hello")


def test_chat_session_ask_gemini_sdk_unavailable():
    """Test that missing SDK is properly reported."""
    config = ChatConfig(
        backend="google",
        model="gemini-pro",
        system_prompt="Test prompt",
        transport="file",
    )
    session = ChatSession(config)

    # Set API key but SDK won't be available
    os.environ["GOOGLE_API_KEY"] = "test-key"
    try:
        # Without mocking, the SDK won't be available
        with pytest.raises(ChatError, match="Google Generative AI SDK unavailable"):
            session.ask("Hello")
    finally:
        os.environ.pop("GOOGLE_API_KEY", None)


@pytest.mark.asyncio
async def test_chat_session_ask_gemini_stream_requires_api_key():
    """Test that Gemini streaming requires GOOGLE_API_KEY."""
    config = ChatConfig(
        backend="google",
        model="gemini-pro",
        system_prompt="Test prompt",
        transport="realtime",
    )
    session = ChatSession(config)

    # Remove GOOGLE_API_KEY if it exists
    old_key = os.environ.pop("GOOGLE_API_KEY", None)
    try:
        with pytest.raises(ChatError, match="GOOGLE_API_KEY is not set"):
            async for _ in session.ask_stream("Hello"):
                pass
    finally:
        if old_key:
            os.environ["GOOGLE_API_KEY"] = old_key


@pytest.mark.asyncio
async def test_chat_session_ask_gemini_stream_sdk_unavailable():
    """Test that missing SDK is properly reported in streaming mode."""
    config = ChatConfig(
        backend="google",
        model="gemini-pro",
        system_prompt="Test prompt",
        transport="realtime",
    )
    session = ChatSession(config)

    # Set API key but SDK won't be available
    os.environ["GOOGLE_API_KEY"] = "test-key"
    try:
        # Without mocking, the SDK won't be available
        with pytest.raises(ChatError, match="Google Generative AI SDK unavailable"):
            async for _ in session.ask_stream("Hello"):
                pass
    finally:
        os.environ.pop("GOOGLE_API_KEY", None)


def test_chat_session_ask_backward_compatibility_echo():
    """Test that echo backend still works (backward compatibility)."""
    config = ChatConfig(
        backend="echo",
        model="gpt-4o-mini",
        system_prompt="Test prompt",
        transport="file",
    )
    session = ChatSession(config)

    reply, history = session.ask("Test message")

    assert "Test message" in reply
    assert len(history) == 2


@pytest.mark.asyncio
async def test_chat_session_ask_stream_backward_compatibility_echo():
    """Test that echo backend streaming still works (backward compatibility)."""
    config = ChatConfig(
        backend="echo",
        model="gpt-4o-mini",
        system_prompt="Test prompt",
        transport="realtime",
    )
    session = ChatSession(config)

    chunks = []
    async for chunk in session.ask_stream("Test message"):
        chunks.append(chunk)

    assert len(chunks) == 1
    assert "Test message" in chunks[0]


def test_chat_session_ask_openai_backend_still_works():
    """Test that OpenAI backend selection still works (no regression)."""
    config = ChatConfig(
        backend="openai",
        model="gpt-4o-mini",
        system_prompt="Test prompt",
        transport="file",
    )
    session = ChatSession(config)

    # Should fail with missing API key (expected behavior)
    with pytest.raises(ChatError, match="OPENAI_API_KEY is not set"):
        session.ask("Hello")


@pytest.mark.asyncio
async def test_chat_session_ask_stream_openai_backend_still_works():
    """Test that OpenAI backend streaming still works (no regression)."""
    config = ChatConfig(
        backend="openai",
        model="gpt-4o-mini",
        system_prompt="Test prompt",
        transport="realtime",
    )
    session = ChatSession(config)

    # Should fail with missing API key (expected behavior)
    with pytest.raises(ChatError, match="OPENAI_API_KEY is not set"):
        async for _ in session.ask_stream("Hello"):
            pass
