# apps/voice/chat.py
"""Chat backends for conversational responses."""

from __future__ import annotations

import os
from dataclasses import dataclass

from . import voice_logging as voice_logging


class ChatError(RuntimeError):
    pass


@dataclass
class ChatConfig:
    backend: str
    model: str
    system_prompt: str
    max_history: int = 4
    # Limit tokenów przekazywany do API (None = bez limitu)
    max_tokens: int | None = None
    # NOWE: tryb transportu. W STRICT mode zabrania REST, gdy "realtime"
    transport: str = "file"  # "file" | "realtime"


@dataclass
class Message:
    role: str
    content: str


class ChatSession:
    def __init__(self, config: ChatConfig, logger: voice_logging.VoiceLogger | None = None):
        self.config = config
        self.logger = logger or voice_logging.get_logger("voice.chat")
        self._history: list[Message] = []

    def ask(self, text: str) -> tuple[str, list[Message]]:
        backend = (self.config.backend or "echo").lower()

        if backend == "openai":
            reply = self._ask_openai(text)
        else:
            # Prosty backend echa – przydatny w trybie offline/testowym
            reply = f"You said: {text.strip()}"

        # aktualizuj historię (user + assistant)
        self._history.append(Message(role="user", content=text))
        self._history.append(Message(role="assistant", content=reply))

        # ogranicz rozmiar historii (pary user/assistant)
        max_pairs = max(0, int(self.config.max_history))
        if max_pairs > 0 and len(self._history) > max_pairs * 2:
            self._history = self._history[-max_pairs * 2 :]

        return reply, list(self._history)

    def _ask_openai(self, text: str) -> str:
        """
        REST-owe wywołanie Chat Completions.
        W STRICT mode blokujemy REST, jeśli transport=realtime.
        """
        # TWARDY BEZPIECZNIK: brak REST, gdy żądany jest realtime
        if (self.config.transport or "").lower() == "realtime":
            raise ChatError("Chat REST disabled when transport=realtime")

        # Minimalna walidacja
        if not self.config.model:
            raise ChatError("OpenAI model not configured")
        if not self.config.backend or self.config.backend.lower() != "openai":
            raise ChatError("OpenAI backend not selected")

        # Klucz API – dla REST wymagany
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ChatError("OPENAI_API_KEY is not set")

        try:
            from openai import OpenAI  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise ChatError(f"OpenAI SDK unavailable: {exc}") from exc

        client = OpenAI(api_key=api_key)

        # Zbuduj listę wiadomości
        messages = [{"role": "system", "content": self.config.system_prompt}]
        # weź ostatnie N par z historii
        max_pairs = max(0, int(self.config.max_history))
        if max_pairs > 0:
            for item in self._history[-max_pairs * 2 :]:
                messages.append({"role": item.role, "content": item.content})
        messages.append({"role": "user", "content": text})

        # Payload do API — DODANE: warunkowe max_tokens
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.6,
        }
        if self.config.max_tokens is not None:
            payload["max_tokens"] = int(self.config.max_tokens)

        # Wywołanie API (REST)
        try:
            self.logger.event("chat.rest.request", model=self.config.model, msg_count=len(messages))
            response = client.chat.completions.create(**payload)
            choice = response.choices[0].message.content if getattr(response, "choices", None) else ""
            text_out = (choice or "").strip()
            self.logger.event("chat.rest.ok", chars=len(text_out))
            return text_out
        except Exception as exc:
            self.logger.event("chat.rest.error", error=str(exc))
            raise ChatError(f"OpenAI chat completion failed: {exc}") from exc

    def reset(self) -> None:
        self._history.clear()
