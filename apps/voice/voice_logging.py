import json
import logging
from datetime import datetime


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.utcfromtimestamp(record.created).isoformat(timespec="milliseconds") + "Z",
            "level": record.levelname,
            "name": record.name,
            "msg": record.getMessage(),
        }

        # Zbierz dodatkowe pola (extra) bez nie-serializowalnych obiektów
        extra = {}
        for k, v in record.__dict__.items():
            if k in (
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
            ):
                continue
            try:
                json.dumps(v)
                extra[k] = v
            except TypeError:
                # np. obiekty websockets (ClientConnection, Frame) → zamieniamy na str()
                extra[k] = str(v)

        if extra:
            payload["data"] = extra

        # KOŃCOWE zabezpieczenie: wszystko co nie-JSON → str()
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_json_logging(level=logging.INFO):
    """Ustaw jednoliniowy JSON logging na podanym poziomie."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    # usuń istniejące handlery, żeby nie dublować
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(level)
    return root


def configure(level=None):
    """
    Kompatybilne API (wołane przez cli.py):
      - przyjmuje level (str/int/None),
      - ustawia JSON logging,
      - ścisza 'websockets' do WARNING,
      - dodaje metodę logger.event(msg, **fields).
    """
    # mapowanie stringów na poziomy
    if isinstance(level, str):
        lvl = getattr(logging, level.upper(), logging.INFO)
    elif isinstance(level, int):
        lvl = level
    else:
        lvl = logging.INFO

    root = setup_json_logging(lvl)

    # ucisz bardzo gadatliwy logger websockets
    logging.getLogger("websockets").setLevel(logging.WARNING)

    # dodaj logger.event jeśli brak
    if not hasattr(logging.Logger, "event"):

        def _event(self, msg: str, **fields):
            # pola trafiają do JsonLogFormatter jako extra
            self.info(msg, extra=fields)

        logging.Logger.event = _event

    return root


def get_logger(name: str = None) -> logging.Logger:
    """
    Zwraca logger o podanej nazwie.
    Jeżeli root nie ma jeszcze handlerów (np. w testach), skonfiguruj go domyślnie.
    """
    root = logging.getLogger()
    if not root.handlers:
        configure(logging.INFO)
    return logging.getLogger(name)
