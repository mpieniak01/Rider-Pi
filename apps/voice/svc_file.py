# apps/voice/svc_file.py
"""Voice service file mode pipeline — STRICT file-only.

Zasady:
- Ten moduł uruchamia wyłącznie ścieżkę plikową (ASR/CHAT/TTS = "file").
- Jeśli w cfg gdziekolwiek ustawiono transport="realtime", przerywamy z kodem 2.
- Przed uruchomieniem wymuszamy "file" w asr/chat/tts, aby uniknąć niespójności.
"""

from __future__ import annotations

from typing import Any


def _assert_file_mode(cfg: dict[str, Any]) -> None:
    """Rzuć wyjątek, jeśli ktokolwiek próbuje wymusić 'realtime' w file-mode."""
    for sec in ("asr", "chat", "tts"):
        sec_cfg = cfg.get(sec) or {}
        if str(sec_cfg.get("transport", "")).lower() == "realtime":
            raise RuntimeError(
                f"[voice.svc_file] ERROR: file-mode only; '{sec}.transport=realtime' niedozwolone w tym trybie."
            )


def _force_transports_file(cfg: dict[str, Any]) -> None:
    """Ustaw transport='file' w asr/chat/tts, jeśli nie ustawiono inaczej."""
    for sec in ("asr", "chat", "tts"):
        sec_cfg = cfg.setdefault(sec, {})
        sec_cfg["transport"] = "file"


def run_listen_file(cfg: dict[str, Any], args) -> int:
    """Run listen mode using file-based pipeline (STRICT file-only)."""
    # Import here to avoid circular imports
    from .service_impl import VoiceService, setup_signals

    try:
        _assert_file_mode(cfg)
    except RuntimeError as e:
        print(str(e))
        return 2

    _force_transports_file(cfg)

    service = VoiceService(cfg)
    setup_signals(service)
    service.listen()
    return 0


def run_once_file(cfg: dict[str, Any], args) -> int:
    """Run once mode using file-based pipeline (STRICT file-only)."""
    # Import here to avoid circular imports
    from .service_impl import VoiceService, setup_signals

    try:
        _assert_file_mode(cfg)
    except RuntimeError as e:
        print(str(e))
        return 2

    _force_transports_file(cfg)

    service = VoiceService(cfg)
    setup_signals(service)
    result = service.once()
    if result:
        print(result.transcript.text)
    return 0
