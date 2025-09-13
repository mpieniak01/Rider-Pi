"""Face emotion normalization helpers."""

ALLOWED = {"happy", "sad", "neutral", "blink"}


def normalize_expr(expr: str) -> str:
    e = (expr or "").strip().lower()
    return e if e in ALLOWED else "neutral"
