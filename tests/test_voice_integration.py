from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.hardware

"""
Integration tests for the streaming voice service.

These tests verify the complete pipeline works without requiring
external API connections.
"""


import os
from unittest.mock import patch

import pytest

from apps.voice.svc_core import _wants_stream, run_listen, run_once


@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False)
def _skip_if_no_device_env():
    if os.environ.get('RUN_DEVICE_TESTS') != '1':
        pytest.skip('Hardware/ALSA tests disabled on CI (set RUN_DEVICE_TESTS=1 to enable).')


def test_streaming_mode_detection():
    """Test that streaming mode is correctly detected."""
    # File mode config
    file_config = {
        "asr": {"backend": "openai", "transport": "file"},
        "chat": {"backend": "openai", "transport": "rest"},
        "tts": {"backend": "openai", "transport": "file"},
    }
    assert _wants_stream(file_config, None) is False

    # Streaming mode config
    stream_config = {
        "asr": {"backend": "openai", "transport": "realtime"},
        "chat": {"backend": "openai", "transport": "rest"},
        "tts": {"backend": "openai", "transport": "file"},
    }
    assert _wants_stream(stream_config, None) is True

    # Mixed mode (should use streaming)
    mixed_config = {
        "asr": {"backend": "openai", "transport": "file"},
        "chat": {"backend": "openai", "transport": "realtime"},
        "tts": {"backend": "openai", "transport": "file"},
    }
    assert _wants_stream(mixed_config, None) is True


def test_file_mode_delegation():
    """Test that file mode is correctly delegated."""
    config = {
        "asr": {"backend": "openai", "transport": "file"},
        "chat": {"backend": "openai", "transport": "rest"},
        "tts": {"backend": "openai", "transport": "file"},
        "capture": {"backend": "alsa"},
        "playback": {"backend": "alsa"},
        "hotword": {"enabled": False},
        "vad": {"enabled": True},
        "service": {},
    }

    # Mock the file mode implementation to avoid actual service creation
    with patch("apps.voice.svc_core.run_listen_file") as mock_file_listen:
        mock_file_listen.return_value = 0

        result = run_listen(config, None)
        assert result == 0
        mock_file_listen.assert_called_once_with(config, None)


@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False)
def test_streaming_mode_delegation_with_api_key():
    """Test that streaming mode is correctly delegated when API key is present."""
    config = {
        "asr": {"backend": "openai", "transport": "realtime"},
        "chat": {"backend": "openai", "transport": "realtime"},
        "tts": {"backend": "openai", "transport": "realtime"},
        "stream": {
            "protocol": "websocket",
            "endpoint": "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview",
            "auth": "env:OPENAI_API_KEY",
        },
        "capture": {"backend": "alsa"},
        "playback": {"backend": "alsa"},
    }

    # Mock the streaming implementation to avoid actual WebSocket connection
    with patch("apps.voice.svc_stream_runner.run_listen_stream") as mock_stream_listen:
        mock_stream_listen.return_value = 0

        result = run_listen(config, None)
        assert result == 0
        mock_stream_listen.assert_called_once_with(config, None)


def test_streaming_mode_fallback_on_import_error():
    """Test fallback to file mode when streaming dependencies are missing."""
    config = {
        "asr": {"backend": "openai", "transport": "realtime"},
        "chat": {"backend": "openai", "transport": "rest"},
        "tts": {"backend": "openai", "transport": "file"},
        "capture": {"backend": "alsa"},
        "playback": {"backend": "alsa"},
        "hotword": {"enabled": False},
        "vad": {"enabled": True},
        "service": {},
    }

    # Mock the svc_stream_runner module import to fail
    with patch.dict("sys.modules", {"apps.voice.svc_stream_runner": None}):
        with patch("apps.voice.svc_core.run_listen_file") as mock_file_listen:
            mock_file_listen.return_value = 0

            result = run_listen(config, None)
            assert result == 0
            mock_file_listen.assert_called_once_with(config, None)


@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False)
def test_once_mode_streaming_delegation():
    """Test that once mode correctly delegates to streaming when configured."""
    config = {
        "asr": {"transport": "realtime"},
        "chat": {"transport": "rest"},
        "tts": {"transport": "file"},
        "stream": {"protocol": "websocket"},
    }

    with patch("apps.voice.svc_stream_runner.run_once_stream") as mock_stream_once:
        mock_stream_once.return_value = 0

        result = run_once(config, None)
        assert result == 0
        mock_stream_once.assert_called_once_with(config, None)


def test_once_mode_file_delegation():
    """Test that once mode correctly delegates to file mode when configured."""
    config = {
        "asr": {"transport": "file"},
        "chat": {"transport": "rest"},
        "tts": {"transport": "file"},
        "capture": {"backend": "alsa"},
        "playback": {"backend": "alsa"},
        "hotword": {"enabled": False},
        "vad": {"enabled": True},
        "service": {},
    }

    with patch("apps.voice.svc_core.run_once_file") as mock_file_once:
        mock_file_once.return_value = 0

        result = run_once(config, None)
        assert result == 0
        mock_file_once.assert_called_once_with(config, None)


if __name__ == "__main__":
    pytest.main([__file__])
