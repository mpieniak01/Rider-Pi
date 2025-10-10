from __future__ import annotations

import os
from typing import Any

"""
apps.voice service API

- Legacy (tymczasowe, na potrzeby testów): klasy z service_impl.
- Nowe API: funkcje run_listen / run_once.
- Shimy: punkty do monkeypatch w testach (ASR, VAD, hotword/PTT, NLU/chat).

Dodatkowo: podczas importu:
- łagodnie próbujemy uzupełnić ENV z ~/.bash_profile (gdy dostępny jest
  moduł apps.voice.env_loader – nie jest to twarda zależność),
- logujemy stan kluczowych zmiennych środowiskowych (bezpiecznie, bez wartości).
"""

# Logowanie dopiero po wczytaniu opcjonalnego ENV – unikamy zbędnych importów.
try:
    from .voice_logging import info as _log_info, warn as _log_warn  # type: ignore
except Exception:  # pragma: no cover
    # Minimalne „no-op” jeśli logger nie jest dostępny w bardzo wczesnym etapie importu.
    def _log_info(name: str, msg: str, data: dict[str, Any] | None = None) -> None:  # type: ignore
        pass

    def _log_warn(name: str, msg: str, data: dict[str, Any] | None = None) -> None:  # type: ignore
        pass


# --- Opcjonalne uzupełnienie ENV z ~/.bash_profile ---------------------------
def _maybe_load_env_from_bash_profile() -> None:
    """
    Łagodne uzupełnienie ENV z ~/.bash_profile (jeśli dostępny moduł).
    Nigdy nie zrywa importu przy błędach.
    """
    try:
        # Nie robimy z tego twardej zależności – jeśli modułu nie ma, pomijamy.
        from .env_loader import (  # type: ignore
            ensure_env_from_bash_profile as _ensure_env_from_bash_profile,
        )
    except Exception:  # pragma: no cover
        _log_info("voice.init", "env.loader.missing", {"src": "env_loader"})
        return

    try:
        _ensure_env_from_bash_profile()
        _log_info("voice.init", "env.loader.ok", {"src": "~/.bash_profile"})
    except Exception:  # pragma: no cover
        _log_warn("voice.init", "env.loader.failed", {"src": "~/.bash_profile"})


_maybe_load_env_from_bash_profile()


def _mask_len(value: str | None) -> int:
    return len(value) if value else 0


def _report_env_state() -> None:
    """
    Bezpieczne logowanie stanu krytycznych zmiennych (bez wypisywania wartości).
    """
    keys = [
        "OPENAI_API_KEY",  # Realtime / Chat
        "OPENAI_BASE_URL",  # niestandardowe endpointy (opcjonalnie)
        "OPENAI_ORG_ID",  # org (opcjonalnie)
        "HTTP_PROXY",  # ewentualne proxy
        "HTTPS_PROXY",
    ]
    data = {k: {"present": bool(os.getenv(k)), "len": _mask_len(os.getenv(k))} for k in keys}
    _log_info("voice.init", "env.state", data)

    if not os.getenv("OPENAI_API_KEY"):
        _log_warn(
            "voice.init",
            "env.missing.key",
            {"var": "OPENAI_API_KEY", "hint": "Ustaw klucz lub zapewnij ładowanie z ~/.bash_profile"},
        )


_report_env_state()

# --- Legacy class-based API (tymczasowo dla zgodności testów) ----------------
# Now imported from svc_file (consolidated in PR#1)
# --- Public functional API (nowe) -------------------------------------------
from .svc_core import run_listen, run_once  # noqa: E402
from .svc_file import (  # noqa: E402
    SpeechTask,
    VoiceResult,
    VoiceService,
)
from .svc_signals import setup_signals  # noqa: E402

# --- Shimy kompatybilności dla testów (monkeypatch w pytest) -----------------
# Elastyczny import transcribe_file -> transcribe
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
