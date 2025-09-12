from __future__ import annotations

import os


def transcribe(_audio: bytes | None) -> tuple[str, str]:
    """Transcribe audio using backend selected by VOICE_ASR_BACKEND."""
    backend = os.getenv("VOICE_ASR_BACKEND", "stub").lower()
    try:
        if backend == "whisper":
            import whisper  # type: ignore  # noqa: F401
            return "whisper stub", "en"
        if backend == "vosk":
            import vosk  # type: ignore  # noqa: F401
            return "vosk stub", "en"
    except Exception:
        pass
    return "", "en"
