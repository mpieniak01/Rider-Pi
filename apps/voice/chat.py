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
        self._history.append(Message(role="user", content=text))
        self._history.append(Message(role="assistant", content=reply))
        if len(self._history) > self.config.max_history * 2:
            self._history = self._history[-self.config.max_history * 2 :]
        return reply, list(self._history)

    def _ask_openai(self, text: str) -> str:
        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover - optional dependency
            raise ChatError(f"OpenAI SDK unavailable: {exc}") from exc
        client = OpenAI()
        messages = [{"role": "system", "content": self.config.system_prompt}]
        for item in self._history[-self.config.max_history * 2 :]:
            messages.append({"role": item.role, "content": item.content})
        messages.append({"role": "user", "content": text})
        response = client.chat.completions.create(model=self.config.model, messages=messages, temperature=0.6)
        choice = response.choices[0].message.content if response.choices else ""
        return (choice or "").strip()

    def reset(self) -> None:
        self._history.clear()
