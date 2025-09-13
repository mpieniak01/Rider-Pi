from __future__ import annotations


def say(payload: dict[str, str]) -> tuple[dict[str, str], int]:
    """Synthesize speech from text (stub)."""
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        return {"ok": False, "error": "text required"}, 400
    voice = payload.get("voice", "default")
    return {"ok": True, "spoken": text, "voice": voice}, 200
