from __future__ import annotations

# Legacy class-based API (tymczasowo dla zgodności testów)
from .service_impl import (
    SpeechTask,
    VoiceResult,
    VoiceService,
    setup_signals,
)

# Public functional API (nowe)
from .svc_core import run_listen, run_once

# --- Shimy kompatybilności dla testów (monkeypatch w pytest) ---
# elastyczny import transcribe_file -> transcribe
try:
    # wariant: apps/asr.py
    from ..asr import transcribe_file as transcribe  # type: ignore[attr-defined]
except Exception:
    try:
        # wariant: apps/voice/asr.py
        from .asr import transcribe_file as transcribe  # type: ignore[attr-defined]
    except Exception:
        # ostateczny fallback: stub (testy i tak monkeypatchują)
        def transcribe(*args, **kwargs):
            raise NotImplementedError("transcribe shim: brak modułu asr.py (apps/asr.py lub apps/voice/asr.py)")


def _record_with_vad(*args, **kwargs):
    """(shim) Punkt patchowania; właściwa logika w svc_audio.capture_once()."""
    raise NotImplementedError("_record_with_vad is test-only shim; patched in tests")


def _wait_hotword_without_capture(*args, **kwargs):
    """(shim) Punkt patchowania dla hotword/PTT."""
    raise NotImplementedError("_wait_hotword_without_capture is test-only shim")


def _handle_intent(*args, **kwargs):
    """(shim) Punkt patchowania dla obsługi intencji."""
    raise NotImplementedError("_handle_intent is test-only shim")


def nlu_chat(*args, **kwargs):
    """(shim) Punkt patchowania dla NLU/chat."""
    raise NotImplementedError("nlu_chat is test-only shim; patched in tests")


__all__ = [
    # nowe API
    "run_listen",
    "run_once",
    # legacy API (tymczasowo dla testów)
    "VoiceService",
    "VoiceResult",
    "SpeechTask",
    "setup_signals",
    # shimy
    "transcribe",
    "_record_with_vad",
    "_wait_hotword_without_capture",
    "_handle_intent",
    "nlu_chat",
]
