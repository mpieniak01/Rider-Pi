# apps/voice/__init__.py
from .audio import ALSAError  # re-eksport z podsystému audio

__all__ = ["ALSAError"]

# Re-eksporty dla stabilności importów po rozbiciu svc_stream.py
try:
    from .transport import ReconnectingTransport  # noqa: F401
except (ImportError, ModuleNotFoundError):
    pass
