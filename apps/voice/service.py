from __future__ import annotations

# --- Shimy kompatybilności dla testów (monkeypatch w pytest) ---
# Testy oczekują, że poniższe symbole istnieją w module `apps.voice.service`,
# dzięki czemu mogą je nadpisać przez monkeypatch.setattr(...).
# `transcribe` – sensowny alias do plikowego ASR, by runtime miał działającą funkcję.
from ..asr import transcribe_file as transcribe  # noqa: F401

# Legacy class-based API (tymczasowo dla zgodności testów)
from .service_impl import (
    SpeechTask,
    VoiceResult,
    VoiceService,
    setup_signals,
)

# Public functional API (nowe)
from .svc_core import run_listen, run_once


def _record_with_vad(*args, **kwargs):
    """(shim) Zastępczy punkt patchowania; właściwa logika przeniesiona do svc_audio.capture_once()."""
    raise NotImplementedError("_record_with_vad is test-only shim; patched in tests")


def _wait_hotword_without_capture(*args, **kwargs):
    """(shim) Hotword/ptt; tutaj tylko punkt patchowania w testach."""
    raise NotImplementedError("_wait_hotword_without_capture is test-only shim")


def _handle_intent(*args, **kwargs):
    """(shim) Obsługa intencji; prawdziwa implementacja przeniesiona, tu tylko stub do patchowania."""
    raise NotImplementedError("_handle_intent is test-only shim")


def nlu_chat(*args, **kwargs):
    """(shim) NLU/chat; w testach podmieniane lambdą."""
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
    # shimy dla kompatybilności testów
    "transcribe",
    "_record_with_vad",
    "_wait_hotword_without_capture",
    "_handle_intent",
    "nlu_chat",
]
