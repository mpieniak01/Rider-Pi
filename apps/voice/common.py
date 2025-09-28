# ruff: noqa: E402  # imports mogą być niżej (shim prelude na górze)

# --- shim: gwarancja logger.event(...) na plain logging.Logger ---
def ensure_event_logger(logger):
    """
    Zapewnia metodę logger.event(name, **fields) na każdym loggerze.
    Jeśli jej brak – dokleja bezpieczny fallback oparty o logger.info().
    Zwraca ten sam obiekt loggera (dla wygody użycia).
    """
    if hasattr(logger, "event") and callable(logger.event):
        return logger

    def _event(name, **fields):
        try:
            import json  # lokalny import – bezpieczny dla E402

            payload = {"event": name, **(fields or {})}
            # Jednolity, prosty format do grep/CI
            logger.info("event=%s data=%s", name, json.dumps(payload, ensure_ascii=False))
        except Exception as ex:  # awaryjnie, gdyby json się wywalił
            logger.info("event=%s data=%r err=%r", name, fields, ex)

    try:
        logger.event = _event
    except Exception:
        # Gdyby setattr był zablokowany (mało prawdopodobne) – trudno, ale nie psujemy wykonania.
        pass
    return logger


def log_event(logger, name, **fields):
    """
    Bezpieczne logowanie zdarzeń.
    Najpierw gwarantuje logger.event(...), potem woła tę metodę.
    """
    logger = ensure_event_logger(logger)
    try:
        return logger.event(name, **fields)  # type: ignore[attr-defined]
    except Exception:
        try:
            # Ostatnia deska ratunku
            logger.warning("%s | %s", name, fields or {})
        except Exception:
            pass


# --- end shim ---


# --- ensure_openai_key: CI-safe helper (pojedyncza definicja) ---
def ensure_openai_key(logger):
    """
    Zwraca klucz OpenAI z env: OPENAI_API_KEY lub OPENAI_KEY.
    Jeśli brak — emituje zdarzenie i zwraca None (testy nie powinny się wywracać).
    """
    import os  # lokalny import, by nie naruszać kolejności innych importów

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
