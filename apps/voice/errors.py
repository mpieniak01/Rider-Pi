"""Domain-specific exceptions for Rider-Pi voice assistant."""

from __future__ import annotations


class VoiceError(Exception):
    """Base exception for voice-related errors."""

    pass


class StreamError(VoiceError):
    """WebSocket/streaming related errors."""

    pass


class AudioError(VoiceError):
    """Audio capture/playback related errors."""

    pass


class ConfigError(VoiceError):
    """Configuration validation errors."""

    pass


class ALSAError(AudioError):
    """ALSA-specific errors."""

    pass


class CaptureError(AudioError):
    """Audio capture errors."""

    pass


class PlaybackError(AudioError):
    """Audio playback errors."""

    pass
