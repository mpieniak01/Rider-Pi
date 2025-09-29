# apps/voice/audio/errors.py
"""Error classes for the audio subsystem (single source of truth)."""

from __future__ import annotations


class ALSAError(RuntimeError):
    """ALSA-related errors (canonical definition used across the package)."""

    pass


__all__ = ["ALSAError"]
