"""Tests for Google Gemini chat integration."""

from __future__ import annotations

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


def test_chat_session_ask_gemini_success():
    """Test successful Gemini chat completion."""
    # Create mock modules
    mock_google = MagicMock()
    mock_genai = MagicMock()

    # Setup mock
    mock_chat = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Hello! How can I help you?"
    mock_chat.send_message.return_value = mock_response

    mock_model = MagicMock()
    mock_model.start_chat.return_value = mock_chat
    mock_genai.GenerativeModel.return_value = mock_model

    config = ChatConfig(
        backend="google",
        model="gemini-pro",
        system_prompt="Test prompt",
        transport="file",
    )
    mock_logger = MagicMock()
    session = ChatSession(config, logger=mock_logger)

    # Set API key
    os.environ["GOOGLE_API_KEY"] = "test-key"
    try:
        # Mock both google and google.generativeai modules
        with patch.dict(sys.modules, {"google": mock_google, "google.generativeai": mock_genai}):
            reply, history = session.ask("Hello")

            # Verify API was configured
            mock_genai.configure.assert_called_once_with(api_key="test-key")

            # Verify model was created with system instruction
            mock_genai.GenerativeModel.assert_called_once_with(
                model_name="gemini-pro",
                system_instruction="Test prompt",
            )

            # Verify chat was started
            mock_model.start_chat.assert_called_once()

            # Verify message was sent
            mock_chat.send_message.assert_called_once_with("Hello")

            # Verify response
            assert reply == "Hello! How can I help you?"
            assert len(history) == 2
            assert history[0].role == "user"
            assert history[0].content == "Hello"
            assert history[1].role == "assistant"
            assert history[1].content == "Hello! How can I help you?"
    finally:
        os.environ.pop("GOOGLE_API_KEY", None)


def test_chat_session_ask_gemini_with_history():
    """Test that Gemini uses conversation history correctly."""
    # Create mock modules
    mock_google = MagicMock()
    mock_genai = MagicMock()

    # Setup mock
    mock_chat = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Second response"
    mock_chat.send_message.return_value = mock_response

    mock_model = MagicMock()
    mock_model.start_chat.return_value = mock_chat
    mock_genai.GenerativeModel.return_value = mock_model

    config = ChatConfig(
        backend="google",
        model="gemini-pro",
        system_prompt="Test prompt",
        max_history=2,
        transport="file",
    )
    mock_logger = MagicMock()
    session = ChatSession(config, logger=mock_logger)

    # Manually add some history
    from apps.voice.chat import Message

    session._history.append(Message(role="user", content="First question"))
    session._history.append(Message(role="assistant", content="First answer"))

    # Set API key
    os.environ["GOOGLE_API_KEY"] = "test-key"
    try:
        with patch.dict(sys.modules, {"google": mock_google, "google.generativeai": mock_genai}):
            session.ask("Second question")

            # Verify chat was started with history
            call_args = mock_model.start_chat.call_args
            history = call_args.kwargs.get("history", [])

            # Should contain previous conversation (assistant mapped to 'model')
            assert len(history) == 2
            assert history[0] == {"role": "user", "parts": ["First question"]}
            assert history[1] == {"role": "model", "parts": ["First answer"]}
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
async def test_chat_session_ask_gemini_stream_success():
    """Test successful Gemini streaming chat completion."""
    # Create mock modules
    mock_google = MagicMock()
    mock_genai = MagicMock()

    # Setup mock streaming response
    async def mock_stream():
        chunks = [
            MagicMock(text="Hello"),
            MagicMock(text=" there"),
            MagicMock(text="!"),
        ]
        for chunk in chunks:
            yield chunk

    mock_chat = MagicMock()
    mock_response = mock_stream()
    mock_chat.send_message_async = AsyncMock(return_value=mock_response)

    mock_model = MagicMock()
    mock_model.start_chat.return_value = mock_chat
    mock_genai.GenerativeModel.return_value = mock_model

    config = ChatConfig(
        backend="google",
        model="gemini-pro",
        system_prompt="Test prompt",
        transport="realtime",
    )
    mock_logger = MagicMock()
    session = ChatSession(config, logger=mock_logger)

    # Set API key
    os.environ["GOOGLE_API_KEY"] = "test-key"
    try:
        with patch.dict(sys.modules, {"google": mock_google, "google.generativeai": mock_genai}):
            chunks = []
            async for chunk in session.ask_stream("Hello"):
                chunks.append(chunk)

            # Verify we got all chunks
            assert chunks == ["Hello", " there", "!"]

            # Verify history was updated correctly
            assert len(session._history) == 2
            assert session._history[0].content == "Hello"
            assert session._history[1].content == "Hello there!"
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

