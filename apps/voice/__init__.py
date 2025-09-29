# apps/voice/__init__.py
from .audio import ALSAError  # re-eksport z podsystému audio

__all__ = ["ALSAError"]
