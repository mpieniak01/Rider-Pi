""" "Structured logging helpers for the voice stack.

The voice stack is spawned either as a CLI tool, a long-running
service, or via the HTTP API.  All of these entry points should rely on
consistent JSON logs so that systemd/journalctl can aggregate events
without extra parsing.  The helpers defined here offer a tiny wrapper on
`logging` that keeps the standard library ergonomics while emitting a
machine friendly payload.

The formatter keeps the surface compact — every log entry contains the
fields `ts`, `level`, `name` and `msg`.  Any keyword arguments passed to
`VoiceLogger.event()` are flattened under the `data` key.  Exceptions are
serialized into `exc` so that stack traces survive across process
boundaries.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

_DEFAULT_LEVEL = "INFO"
_STD_ATTRS = {
    "name",
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
    "message",
}


class _JsonFormatter(logging.Formatter):
    """Serialize log records into JSON lines."""

    default_time_format = "%Y-%m-%dT%H:%M:%S"

    def format(self, record: logging.LogRecord) -> str:
        # używamy UTC, bo dopisujemy 'Z'
        ts = time.strftime(self.default_time_format, time.gmtime(record.created))
        payload: dict[str, Any] = {
            "ts": f"{ts}.{int(record.msecs):03d}Z",
            "level": record.levelname,
            "name": record.name,
            "msg": record.getMessage(),
        }

        # Zbierz dodatkowe pola i spłaszcz do 'data'
        extras = {k: v for k, v in record.__dict__.items() if k not in _STD_ATTRS}
        if extras:
            # Jeżeli logger podał 'data' (np. extra={"data": {...}}), weź je wprost.
            data = extras.pop("data", None)
            if isinstance(data, dict):
                # Połącz z resztą extras (gdyby coś jeszcze zostało)
                payload["data"] = {**data, **extras} if extras else data
            elif data is not None:
                payload["data"] = data if not extras else {"_": data, **extras}
            elif extras:
                payload["data"] = extras

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def _level_from_env(default: str = _DEFAULT_LEVEL) -> str:
    level = os.getenv("VOICE_LOG_LEVEL", default)
    return level.upper()


def configure(level: str | None = None) -> None:
    """Configure the root logger to emit JSON to stdout."""
    resolved = (level or _level_from_env()).upper()
    stream = logging.StreamHandler(stream=sys.stdout)
    stream.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(stream)
    root.setLevel(getattr(logging, resolved, logging.INFO))


@dataclass
class VoiceLogger:
    """Convenience wrapper adding structured `event` helper."""

    logger: logging.Logger

    def event(self, msg: str, **fields: Any) -> None:
        # Pola trafiają pod 'data' (formatter je spłaszczy na poziomie głównym).
        if fields:
            self.logger.info(msg, extra={"data": fields})
        else:
            self.logger.info(msg)

    def error(self, msg: str, **fields: Any) -> None:
        if fields:
            self.logger.error(msg, extra={"data": fields})
        else:
            self.logger.error(msg)

    def warning(self, msg: str, **fields: Any) -> None:
        if fields:
            self.logger.warning(msg, extra={"data": fields})
        else:
            self.logger.warning(msg)

    def debug(self, msg: str, **fields: Any) -> None:
        if fields:
            self.logger.debug(msg, extra={"data": fields})
        else:
            self.logger.debug(msg)


def get_logger(name: str) -> VoiceLogger:
    return VoiceLogger(logging.getLogger(name))


def init(name: str = "voice", level: str | None = None) -> VoiceLogger:
    configure(level)
    return get_logger(name)
