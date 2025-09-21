from __future__ import annotations

import os

from . import voice_logging as vlog


def ensure_openai_key(logger: vlog.VoiceLogger | None = None) -> str | None:
    """
    Zwraca OPENAI_API_KEY (albo OPENAI_KEY jako fallback).
    Jeśli brak – zaloguje błąd i zwróci None.
    """
    logger = logger or vlog.get_logger("voice.common")
    key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY")
    if not key:
        logger.error(
            "openai.key.missing", hint="Ustaw zmienną środowiskową OPENAI_API_KEY (lub OPENAI_KEY)"
        )
        return None
    return key
