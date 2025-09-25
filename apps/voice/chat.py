# apps/voice/chat.py
"""Chat backends for conversational responses."""

from __future__ import annotations

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
    # NOWE: limit tokenów przekazywany DO API (None = bez limitu)
    max_tokens: int | None = None


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
        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover - optional dependency
            raise ChatError(f"OpenAI SDK unavailable: {exc}") from exc

        client = OpenAI()

        # zbuduj listę wiadomości
        messages = [{"role": "system", "content": self.config.system_prompt}]
        # weź ostatnie N par z historii
        max_pairs = max(0, int(self.config.max_history))
        if max_pairs > 0:
            for item in self._history[-max_pairs * 2 :]:
                messages.append({"role": item.role, "content": item.content})
        messages.append({"role": "user", "content": text})

        # payload do API — DODANE: warunkowe max_tokens
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.6,
        }
        if self.config.max_tokens is not None:
            payload["max_tokens"] = int(self.config.max_tokens)

        # wywołanie API
        response = client.chat.completions.create(**payload)
        choice = response.choices[0].message.content if getattr(response, "choices", None) else ""
        return (choice or "").strip()

    def reset(self) -> None:
        self._history.clear()
