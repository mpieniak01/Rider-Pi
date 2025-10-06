# tests/test_voice_errors.py
"""Tests for voice domain errors (PR-3)."""

import pytest

from apps.voice.errors import (
    ALSAError,
    AudioError,
    BackpressureExceeded,
    BadAudioFormat,
    CaptureError,
    ConfigError,
    PlaybackError,
    StreamError,
    VoiceError,
    WsClosed,
)


def test_voice_error_base():
    """Test base VoiceError exception."""
    error = VoiceError("test error")
    assert isinstance(error, Exception)
    assert str(error) == "test error"


def test_stream_error_hierarchy():
    """Test StreamError is a VoiceError."""
    error = StreamError("stream error")
    assert isinstance(error, VoiceError)
    assert isinstance(error, Exception)


def test_audio_error_hierarchy():
    """Test AudioError is a VoiceError."""
    error = AudioError("audio error")
    assert isinstance(error, VoiceError)
    assert isinstance(error, Exception)


def test_config_error_hierarchy():
    """Test ConfigError is a VoiceError."""
    error = ConfigError("config error")
    assert isinstance(error, VoiceError)
    assert isinstance(error, Exception)


def test_alsa_error_hierarchy():
    """Test ALSAError is an AudioError and VoiceError."""
    error = ALSAError("alsa error")
    assert isinstance(error, AudioError)
    assert isinstance(error, VoiceError)
    assert isinstance(error, Exception)


def test_capture_error_hierarchy():
    """Test CaptureError is an AudioError and VoiceError."""
    error = CaptureError("capture error")
    assert isinstance(error, AudioError)
    assert isinstance(error, VoiceError)
    assert isinstance(error, Exception)


def test_playback_error_hierarchy():
    """Test PlaybackError is an AudioError and VoiceError."""
    error = PlaybackError("playback error")
    assert isinstance(error, AudioError)
    assert isinstance(error, VoiceError)
    assert isinstance(error, Exception)


def test_ws_closed_hierarchy():
    """Test WsClosed is a StreamError and VoiceError."""
    error = WsClosed("WebSocket closed unexpectedly")
    assert isinstance(error, StreamError)
    assert isinstance(error, VoiceError)
    assert isinstance(error, Exception)


def test_bad_audio_format_hierarchy():
    """Test BadAudioFormat is an AudioError and VoiceError."""
    error = BadAudioFormat("Invalid audio format: expected PCM16, got PCM8")
    assert isinstance(error, AudioError)
    assert isinstance(error, VoiceError)
    assert isinstance(error, Exception)


def test_backpressure_exceeded_hierarchy():
    """Test BackpressureExceeded is a StreamError and VoiceError."""
    error = BackpressureExceeded("Too many dropped chunks: 100")
    assert isinstance(error, StreamError)
    assert isinstance(error, VoiceError)
    assert isinstance(error, Exception)


def test_all_errors_can_be_raised():
    """Test that all error types can be raised and caught."""
    errors = [
        VoiceError,
        StreamError,
        AudioError,
        ConfigError,
        ALSAError,
        CaptureError,
        PlaybackError,
        WsClosed,
        BadAudioFormat,
        BackpressureExceeded,
    ]

    for error_class in errors:
        with pytest.raises(error_class):
            raise error_class("test error")


def test_error_with_custom_message():
    """Test errors with custom messages."""
    ws_error = WsClosed("Connection lost: code 1006")
    assert "1006" in str(ws_error)

    format_error = BadAudioFormat("Sample rate mismatch: 48000 vs 16000")
    assert "48000" in str(format_error)
    assert "16000" in str(format_error)

    backpressure_error = BackpressureExceeded("Dropped 50 audio chunks in 1 second")
    assert "50" in str(backpressure_error)


def test_catch_specific_error_type():
    """Test catching specific error types."""
    # Test catching WsClosed specifically
    try:
        raise WsClosed("Test WS close")
    except WsClosed as e:
        assert "Test WS close" in str(e)
    except StreamError:
        pytest.fail("Should have caught WsClosed, not generic StreamError")

    # Test catching BadAudioFormat specifically
    try:
        raise BadAudioFormat("Test format error")
    except BadAudioFormat as e:
        assert "Test format error" in str(e)
    except AudioError:
        pytest.fail("Should have caught BadAudioFormat, not generic AudioError")


def test_catch_parent_error_type():
    """Test that parent error types can catch child errors."""
    # WsClosed should be caught by StreamError
    try:
        raise WsClosed("Test")
    except StreamError:
        pass  # Expected
    except Exception:
        pytest.fail("Should have caught as StreamError")

    # BadAudioFormat should be caught by AudioError
    try:
        raise BadAudioFormat("Test")
    except AudioError:
        pass  # Expected
    except Exception:
        pytest.fail("Should have caught as AudioError")

    # All should be caught by VoiceError
    try:
        raise BackpressureExceeded("Test")
    except VoiceError:
        pass  # Expected
    except Exception:
        pytest.fail("Should have caught as VoiceError")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
