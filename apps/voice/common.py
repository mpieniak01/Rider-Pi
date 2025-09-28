# ruff: noqa: E402  # imports may appear below (shim prelude at top)

# --- shim: safe event logging for plain logging.Logger ---
def log_event(logger, name: str, **fields):
    """
    Safe event logging:
    - if logger has .event() → use it
    - else: fallback to .warning with structured fields
    """
    fn = getattr(logger, "event", None)
    if callable(fn):
        try:
            return fn(name, **fields)
        except Exception:
            pass
    try:
        logger.warning("%s | %s", name, fields or {})
    except Exception:
        pass


# --- end shim ---


# --- ensure_openai_key: CI-safe helper (no typing hints) ---
def ensure_openai_key(logger):
    """
    Zwraca klucz OpenAI z env: OPENAI_API_KEY lub OPENAI_KEY.
    Jeśli brak — loguje zdarzenie i zwraca None (CI nie powinno się wysypywać).
    """
    import os  # lokalny import, by nie psuć kolejności importów modułu

    key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY")
    if not key:
        try:
            log_event(
                logger,
                "openai.key.missing",
                hint="Ustaw zmienną OPENAI_API_KEY (lub OPENAI_KEY).",
            )
        except Exception:
            pass
        return None
    return key


# --- end ensure_openai_key ---
