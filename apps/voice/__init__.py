"""Public voice exports load only when used, never for goal/LED metadata."""

from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "ALSAError": "audio",
    "AudioChunkProcessor": "stream_chunks",
    "VoiceError": "errors",
    "WsClosed": "errors",
    "BadAudioFormat": "errors",
    "BackpressureExceeded": "errors",
    "SessionPreferences": "session_prefs",
    "build_session_preferences": "session_prefs",
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    value = getattr(import_module("." + _EXPORTS[name], __name__), name)
    globals()[name] = value
    return value
