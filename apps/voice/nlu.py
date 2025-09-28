# apps/voice/nlu.py
""" "NLU routing: command or chat."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from . import voice_logging as voice_logging
from .common import ensure_event_logger  # ⬅️ shim do .event(...)

COMMAND_PATTERNS = {
    "stop": re.compile(r"\b(stop|stój|zatrzymaj)\b", re.IGNORECASE),
    "forward": re.compile(r"\b(go\s+forward|naprz(ó|o)d|forward)\b", re.IGNORECASE),
    "back": re.compile(r"\b(go\s+back|wstecz|cofnij)\b", re.IGNORECASE),
    "left": re.compile(r"\b(turn\s+left|w\s+lewo)\b", re.IGNORECASE),
    "right": re.compile(r"\b(turn\s+right|w\s+prawo)\b", re.IGNORECASE),
}


@dataclass
class NLUConfig:
    chat_threshold: float
    command_keywords: dict[str, Iterable[str]]
    llm_model: str


@dataclass
class Intent:
    kind: str
    payload: dict[str, Any]


class NLURouter:
    def __init__(self, config: NLUConfig, logger: voice_logging.VoiceLogger | None = None):
        self.config = config
        base_logger = logger or voice_logging.get_logger("voice.nlu")
        self.logger = ensure_event_logger(base_logger)  # ⬅️ gwarantuj logger.event(...)
        self.patterns = dict(COMMAND_PATTERNS)
        for command, keywords in config.command_keywords.items():
            if command in self.patterns:
                continue
            pattern = re.compile(r"|".join(re.escape(k) for k in keywords), re.IGNORECASE)
            self.patterns[command] = pattern

    def route(self, text: str) -> Intent:
        normalized = text.strip()
        if not normalized:
            return Intent(kind="chat", payload={"text": text})
        for name, pattern in self.patterns.items():
            if pattern.search(normalized):
                self.logger.event("nlu.command", command=name)
                return Intent(kind="command", payload={"name": name, "text": normalized})
        self.logger.event("nlu.chat")
        return Intent(kind="chat", payload={"text": normalized})
