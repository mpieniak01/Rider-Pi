from __future__ import annotations

"""
apps.voice package API

- Legacy (tymczasowe, na potrzeby testów): klasy z service_impl.
- Nowe API: funkcje run_listen / run_once.
- Shimy: punkty do monkeypatch w testach (ASR, VAD, hotword/PTT, NLU/chat).

Dodatkowo: na etapie importu próbujemy bezpiecznie uzupełnić ENV
(OPENAI_API_KEY, itp.) z ~/.bash_profile, jeśli dostępny jest moduł
apps.voice.env_loader (nie jest to twarda zależność).
"""

# --- Opcjonalne uzupełnienie ENV z ~/.bash_profile ---------------------------
try:
    # Nie robimy z tego twardej zależności – jeśli modułu nie ma, pomijamy.
    from .env_loader import ensure_env_from_bash_profile as _ensure_env_from_bash_profile  # type: ignore
except Exception:  # pragma: no cover
    _ensure_env_from_bash_profile = None  # type: ignore[assignment]

if _ensure_env_from_bash_profile:
    # Łagodne uzupełnienie brakujących zmiennych; brak skutku ubocznego, gdy ENV kompletne.
    try:
        _ensure_env_from_bash_profile()
    except Exception:
        # Nigdy nie zrywamy importu pakietu, jeżeli profil jest niedostępny.
        pass

# --- Legacy class-based API (tymczasowo dla zgodności testów) ----------------
from .service_impl import (  # noqa: E402
    SpeechTask,
    VoiceResult,
    VoiceService,
    setup_signals,
)

# --- Public functional API (nowe) -------------------------------------------
from .svc_core import run_listen, run_once  # noqa: E402

# --- Shimy kompatybilności dla testów (monkeypatch w pytest) -----------------
# elastyczny import transcribe_file -> transcribe
try:
    # wariant: apps/asr.py (poza pakietem voice)
    from ..asr import transcribe_file as transcribe  # type: ignore[attr-defined]
except Exception:
    try:
        # wariant: apps/voice/asr.py (wewnątrz pakietu voice)
        from .asr import transcribe_file as transcribe  # type: ignore[attr-defined]
    except Exception:

        def transcribe(*args, **kwargs):  # type: ignore[no-redef]
            """Stub: testy podmieniają monkeypatchem."""
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
