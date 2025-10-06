# apps/voice/__init__.py
from .audio import ALSAError  # re-eksport z podsystemu audio
from .errors import (  # PR-3: domain-specific errors
    BackpressureExceeded,
    BadAudioFormat,
    VoiceError,
    WsClosed,
)
from .session_prefs import SessionPreferences, build_session_preferences  # PR-3: session config
from .state import StreamingVoicePTTMixin  # noqa: F401
from .stream_chunks import AudioChunkProcessor  # noqa: F401

# Re-exports from svc_stream refactoring (Issue #58 - minimal split)
from .transport import StreamingVoiceTransportMixin  # noqa: F401

__all__ = [
    "ALSAError",
    "StreamingVoiceTransportMixin",
    "StreamingVoicePTTMixin",
    "AudioChunkProcessor",
    "VoiceError",
    "WsClosed",
    "BadAudioFormat",
    "BackpressureExceeded",
    "SessionPreferences",
    "build_session_preferences",
]
