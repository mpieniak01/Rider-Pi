from __future__ import annotations

import time

from .asr import transcribe


def capture(sec: float) -> tuple[dict[str, object], int]:
    """Record audio for sec seconds and run ASR (stub)."""
    if not (0.5 <= sec <= 6.0):
        return {"ok": False, "error": "bad sec"}, 400
    start = time.time()
    text, lang = transcribe(None)
    dur = time.time() - start
    return {"ok": True, "text": text, "lang": lang, "dur_s": round(dur, 3)}, 200
