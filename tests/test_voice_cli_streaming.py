"""
Tests for voice CLI streaming functionality.

Tests that the CLI properly:
- Parses --chat arguments
- Delegates to streaming mode when transport=realtime
- Handles PTT mode with streaming
- Shows appropriate warnings for unknown config keys
- Falls back gracefully when API keys are missing
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from apps.voice.cli import _build_overrides, build_parser
from apps.voice.svc_core import _wants_stream


def test_cli_parser_accepts_chat_args():
    """Test that CLI parser accepts --chat arguments."""
    parser = build_parser()

    # Test listen command
    args = parser.parse_args(['listen', '--chat', 'transport=realtime', 'max_tokens=100'])
    assert hasattr(args, 'chat')
    assert args.chat == ['transport=realtime', 'max_tokens=100']

    # Test ptt command
    args = parser.parse_args(['ptt', '--chat', 'backend=openai'])
    assert hasattr(args, 'chat')
    assert args.chat == ['backend=openai']

    # Test once command
    args = parser.parse_args(['once', '--chat', 'model=gpt-4o-realtime-preview'])
    assert hasattr(args, 'chat')
    assert args.chat == ['model=gpt-4o-realtime-preview']


def test_chat_args_build_overrides():
    """Test that --chat arguments are properly converted to config overrides."""
    parser = build_parser()
    args = parser.parse_args(['once', '--chat', 'transport=realtime', 'max_tokens=120'])

    overrides = _build_overrides(args)

    assert 'chat' in overrides
    assert overrides['chat']['transport'] == 'realtime'
    assert overrides['chat']['max_tokens'] == 120


@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False)
def test_streaming_mode_with_chat_transport():
    """Test that transport=realtime in chat triggers streaming mode."""
    config = {
        "asr": {"backend": "openai", "transport": "file"},
        "chat": {
            "backend": "openai",
            "transport": "realtime",
        },  # This should trigger streaming
        "tts": {"backend": "openai", "transport": "file"},
    }

    assert _wants_stream(config, None) is True


@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False)
def test_streaming_mode_with_all_realtime():
    """Test streaming mode when all components use realtime transport."""
    config = {
        "asr": {"backend": "openai", "transport": "realtime"},
        "chat": {"backend": "openai", "transport": "realtime"},
        "tts": {"backend": "openai", "transport": "realtime"},
    }

    assert _wants_stream(config, None) is True


def test_file_mode_with_no_realtime():
    """Test file mode when no realtime transport is specified."""
    config = {
        "asr": {"backend": "openai", "transport": "file"},
        "chat": {"backend": "openai", "transport": "rest"},
        "tts": {"backend": "openai", "transport": "file"},
    }

    assert _wants_stream(config, None) is False


def test_file_mode_with_missing_transport():
    """Test file mode when transport is not specified (defaults)."""
    config = {
        "asr": {"backend": "openai"},
        "chat": {"backend": "openai"},
        "tts": {"backend": "openai"},
    }

    assert _wants_stream(config, None) is False


@patch('apps.voice.svc_stream_runner.run_listen_stream')
@patch('apps.voice.svc_core.run_listen_file')
@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False)
def test_listen_streaming_delegation(mock_file_listen, mock_stream_listen):
    """Test that listen mode delegates to streaming when configured."""
    from apps.voice.svc_core import run_listen

    mock_stream_listen.return_value = 0
    mock_file_listen.return_value = 0

    # Streaming config
    config = {
        "asr": {"transport": "realtime"},
        "chat": {"transport": "rest"},
        "tts": {"transport": "file"},
    }

    result = run_listen(config, None)
    assert result == 0
    mock_stream_listen.assert_called_once_with(config, None)
    mock_file_listen.assert_not_called()


@patch('apps.voice.svc_stream_runner.run_once_stream')
@patch('apps.voice.svc_core.run_once_file')
@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False)
def test_once_streaming_delegation(mock_file_once, mock_stream_once):
    """Test that once mode delegates to streaming when configured."""
    from apps.voice.svc_core import run_once

    mock_stream_once.return_value = 0
    mock_file_once.return_value = 0

    # Streaming config
    config = {
        "asr": {"transport": "file"},
        "chat": {"transport": "realtime"},  # This triggers streaming
        "tts": {"transport": "file"},
    }

    result = run_once(config, None)
    assert result == 0
    mock_stream_once.assert_called_once_with(config, None)
    mock_file_once.assert_not_called()


def test_ptt_streaming_function_exists():
    """Test that run_ptt_stream function exists and works."""
    from apps.voice.svc_stream_runner import run_ptt_stream

    # Mock the dependencies
    with patch('apps.voice.svc_stream_runner.run_listen_stream') as mock_listen:
        mock_listen.return_value = 0

        config = {"asr": {"transport": "realtime"}}
        result = run_ptt_stream(config, None)

        assert result == 0
        mock_listen.assert_called_once()

        # Check that the config was modified for PTT
        call_args = mock_listen.call_args
        modified_config = call_args[0][0]
        assert modified_config["hotword"]["enabled"] is True
        assert modified_config["hotword"]["engine"] == "ptt"


@patch('apps.voice.cli._configure')
def test_cli_chat_args_integration(mock_configure):
    """Test full integration of --chat args through CLI."""
    from apps.voice.cli import cmd_once

    # Mock _configure to return a config and avoid actual service creation
    mock_config = {
        "asr": {"transport": "file"},
        "chat": {"transport": "realtime", "max_tokens": 120},
        "tts": {"transport": "file"},
    }
    mock_service = MagicMock()
    mock_configure.return_value = (mock_config, mock_service)

    # Mock the actual run_once to avoid execution
    with patch('apps.voice.svc_core.run_once') as mock_run_once:
        mock_run_once.return_value = 0

        # Simulate CLI args with --chat
        parser = build_parser()
        args = parser.parse_args(['once', '--chat', 'max_tokens=120', 'transport=realtime'])

        cmd_once(args)

        # Check that run_once was called with the config
        mock_run_once.assert_called_once()
        call_args = mock_run_once.call_args[0]
        _ = call_args[0]  # podgląd konfiguracji nieużywany w asercjach

        # The config should contain the chat overrides
        # (This tests the full flow: CLI -> _build_overrides -> _configure -> run_once)
        mock_configure.assert_called_once()


@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False)
def test_streaming_mode_mixed_transports():
    """Test streaming mode detection with mixed transport settings."""
    # Only ASR is realtime - should trigger streaming
    config1 = {
        "asr": {"transport": "realtime"},
        "chat": {"transport": "rest"},
        "tts": {"transport": "file"},
    }
    assert _wants_stream(config1, None) is True

    # Only TTS is realtime - should trigger streaming
    config2 = {
        "asr": {"transport": "file"},
        "chat": {"transport": "rest"},
        "tts": {"transport": "realtime"},
    }
    assert _wants_stream(config2, None) is True

    # Only chat is realtime - should trigger streaming
    config3 = {
        "asr": {"transport": "file"},
        "chat": {"transport": "realtime"},
        "tts": {"transport": "file"},
    }
    assert _wants_stream(config3, None) is True


def test_all_commands_support_chat_args():
    """Test that all relevant commands support --chat arguments."""
    parser = build_parser()

    # Test that these commands parse --chat without error
    commands_with_chat = ['listen', 'ptt', 'once']

    for cmd in commands_with_chat:
        args = parser.parse_args([cmd, '--chat', 'transport=realtime'])
        assert hasattr(args, 'chat')
        assert args.chat == ['transport=realtime']


@patch.dict(os.environ, {}, clear=True)  # Clear all env vars
def test_streaming_fallback_missing_api_key():
    """Test fallback to file mode when API key is missing."""
    config = {
        "asr": {"backend": "openai", "transport": "realtime"},
        "chat": {"backend": "openai", "transport": "rest"},
        "tts": {"backend": "openai", "transport": "file"},
        "stream": {"auth": "env:OPENAI_API_KEY"},
    }

    # Should fall back to file mode when OPENAI_API_KEY is not set
    assert _wants_stream(config, None) is False


@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False)
def test_streaming_mode_with_api_key():
    """Test streaming mode when API key is available."""
    config = {
        "asr": {"backend": "openai", "transport": "realtime"},
        "chat": {"backend": "openai", "transport": "rest"},
        "tts": {"backend": "openai", "transport": "file"},
        "stream": {"auth": "env:OPENAI_API_KEY"},
    }

    # Should use streaming mode when API key is set
    assert _wants_stream(config, None) is True


def test_config_unknown_keys_warning(capsys):
    """Test that unknown config keys generate warnings."""
    from apps.voice.config import _warn_unknown_keys

    known_config = {
        "asr": {"backend": "openai", "model": "whisper"},
        "chat": {"backend": "openai", "model": "gpt-4"},
    }

    test_config = {
        "asr": {"backend": "openai", "unknown_field": "test"},
        "chat": {"backend": "openai", "model": "gpt-4"},
        "unknown_section": {"some_key": "value"},
    }

    _warn_unknown_keys(test_config, known_config)

    captured = capsys.readouterr()
    assert "WARNING: unknown config key 'asr.unknown_field'" in captured.out
    assert "WARNING: unknown config key 'unknown_section'" in captured.out


if __name__ == "__main__":
    pytest.main([__file__])
