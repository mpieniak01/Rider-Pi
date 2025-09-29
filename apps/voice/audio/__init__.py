# apps/voice/audio/__init__.py
"""Audio package for Rider-Pi voice (ALSA helpers, capture/playback, errors)."""

# --- re-export canonical ALSAError (musi być jako pierwsze) ---
from .alsa import ensure_free, probe_devices, reset_streams, resolved_alsa
from .errors import ALSAError  # noqa: F401

__all__ = [
    "ALSAError",
    "ensure_free",
    "probe_devices",
    "reset_streams",
    "resolved_alsa",
]
