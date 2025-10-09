"""Tests for streaming chat functionality."""

from __future__ import annotations

import pytest

from apps.voice.chat import ChatConfig, ChatSession


@pytest.mark.asyncio
async def test_chat_session_ask_stream_echo():
    """Test streaming chat with echo backend."""
    config = ChatConfig(
        backend="echo",
        model="gpt-4o-mini",
        system_prompt="Test prompt",
        transport="realtime",
    )
    session = ChatSession(config)

    chunks = []
    async for chunk in session.ask_stream("Hello world"):
        chunks.append(chunk)

    # Echo backend should return the full message as one chunk
    assert len(chunks) == 1
    assert "Hello world" in chunks[0]
    assert len(session._history) == 2  # user + assistant


@pytest.mark.asyncio
async def test_chat_session_ask_stream_history():
    """Test that streaming chat maintains history correctly."""
    config = ChatConfig(
        backend="echo",
        model="gpt-4o-mini",
        system_prompt="Test prompt",
        max_history=2,
        transport="realtime",
    )
    session = ChatSession(config)

    # First interaction
    chunks = []
    async for chunk in session.ask_stream("First"):
        chunks.append(chunk)

    assert len(session._history) == 2

    # Second interaction
    chunks = []
    async for chunk in session.ask_stream("Second"):
        chunks.append(chunk)

    assert len(session._history) == 4

    # Third interaction - should maintain max_history
    chunks = []
    async for chunk in session.ask_stream("Third"):
        chunks.append(chunk)

    # max_history=2 means 2 pairs (4 messages total)
    assert len(session._history) == 4
    # Oldest messages should be dropped
    assert session._history[0].content == "Second"


def test_chat_session_ask_sync_still_works():
    """Test that synchronous ask() still works for backward compatibility."""
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
    assert history[0].role == "user"
    assert history[1].role == "assistant"
