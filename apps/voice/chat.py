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
    # STRICT: dla transport="realtime" blokujemy REST (ask), ale pozwalamy na streaming (ask_stream)
    transport: str = "file"  # "file" | "realtime"


@dataclass
class Message:
    role: str
    content: str


class ChatSession:
    def __init__(
        self,
        config: ChatConfig,
        logger: voice_logging.VoiceLogger | None = None,
    ):
        self.config = config
        self.logger = logger or voice_logging.get_logger("voice.chat")
        self._history: list[Message] = []

    # --- bezpieczny wrapper na zdarzenia logów ---------------------------------
    def _evt(self, name: str, **kv) -> None:
        """
        Użyj logger.event, jeśli dostępny (nasz adapter). W przeciwnym razie zapisz .info.
        Logowanie nie może psuć logiki ani testów – wszelkie wyjątki są ignorowane.
        """
        try:
            if hasattr(self.logger, "event"):
                # type: ignore[attr-defined] — w adapterze istnieje 'event'
                self.logger.event(name, **kv)  # type: ignore[attr-defined]
            else:
                self.logger.info("%s %s", name, kv)
        except Exception:
            pass

    def ask(self, text: str) -> tuple[str, list[Message]]:
        backend = (self.config.backend or "echo").lower()

        if backend == "openai":
            reply = self._ask_openai(text)
        elif backend == "google":
            reply = self._ask_gemini(text)
        else:
            # Prosty backend echa – przydatny offline/testowo
            reply = f"You said: {text.strip()}"

        # aktualizuj historię (user + assistant)
        self._history.append(Message(role="user", content=text))
        self._history.append(Message(role="assistant", content=reply))

        # ogranicz rozmiar historii (pary user/assistant)
        max_pairs = max(0, int(self.config.max_history))
        if max_pairs > 0 and len(self._history) > max_pairs * 2:
            self._history = self._history[-max_pairs * 2 :]

        return reply, list(self._history)

    async def ask_stream(self, text: str):
        """
        Asynchroniczne wywołanie chat completions ze streamingiem.
        Zwraca async generator produkujący fragmenty (tokeny) odpowiedzi.
        Używane typowo przy transport="realtime".
        """
        backend = (self.config.backend or "echo").lower()

        # Dodaj wiadomość użytkownika do historii
        self._history.append(Message(role="user", content=text))

        if backend == "openai":
            # Streamujące wywołanie OpenAI
            full_reply = ""
            async for chunk in self._ask_openai_stream(text):
                full_reply += chunk
                yield chunk

            # Zapisz pełną odpowiedź w historii
            self._history.append(Message(role="assistant", content=full_reply))

        elif backend == "google":
            # Quasi-streaming dla Google Gemini
            full_reply = ""
            async for chunk in self._ask_gemini_stream(text):
                full_reply += chunk
                yield chunk

            # Zapisz pełną odpowiedź w historii
            self._history.append(Message(role="assistant", content=full_reply))

        else:
            # Echo backend — zwróć od razu całą odpowiedź
            reply = f"You said: {text.strip()}"
            self._history.append(Message(role="assistant", content=reply))
            yield reply

        # Ogranicz rozmiar historii (po dodaniu odpowiedzi)
        max_pairs = max(0, int(self.config.max_history))
        if max_pairs > 0 and len(self._history) > max_pairs * 2:
            self._history = self._history[-max_pairs * 2 :]

    def _ask_openai(self, text: str) -> str:
        """
        REST-owe wywołanie Chat Completions.
        W STRICT mode blokujemy REST, jeśli transport="realtime".
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
        except Exception as exc:  # pragma: no cover - opcjonalna zależność
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

        # Payload do API — warunkowe max_tokens
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.6,
        }
        if self.config.max_tokens is not None:
            payload["max_tokens"] = int(self.config.max_tokens)

        # Wywołanie API (REST)
        try:
            self._evt("chat.rest.request", model=self.config.model, msg_count=len(messages))
            response = client.chat.completions.create(**payload)
            choice = response.choices[0].message.content if getattr(response, "choices", None) else ""
            text_out = (choice or "").strip()
            self._evt("chat.rest.ok", chars=len(text_out))
            return text_out
        except Exception as exc:
            self._evt("chat.rest.error", error=str(exc))
            raise ChatError(f"OpenAI chat completion failed: {exc}") from exc

    def _ask_gemini(self, text: str) -> str:
        """
        REST-owe wywołanie Google Gemini API.
        W STRICT mode blokujemy REST, jeśli transport="realtime".
        """
        # TWARDY BEZPIECZNIK: brak REST, gdy żądany jest realtime
        if (self.config.transport or "").lower() == "realtime":
            raise ChatError("Chat REST disabled when transport=realtime")

        # Minimalna walidacja
        if not self.config.model:
            raise ChatError("Google model not configured")
        if not self.config.backend or self.config.backend.lower() != "google":
            raise ChatError("Google backend not selected")

        # Klucz API – dla REST wymagany
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise ChatError("GOOGLE_API_KEY is not set")

        try:
            import google.generativeai as genai  # type: ignore
        except Exception as exc:  # pragma: no cover - opcjonalna zależność
            raise ChatError(f"Google Generative AI SDK unavailable: {exc}") from exc

        # Konfiguruj API
        genai.configure(api_key=api_key)

        # Zbuduj historię konwersacji dla Gemini
        # Gemini używa formatu: {'role': 'user'|'model', 'parts': ['text']}
        history = []
        max_pairs = max(0, int(self.config.max_history))
        if max_pairs > 0:
            for item in self._history[-max_pairs * 2 :]:
                # Mapuj 'assistant' na 'model' dla Gemini
                role = "model" if item.role == "assistant" else item.role
                history.append({"role": role, "parts": [item.content]})

        # Wywołanie API (REST)
        try:
            self._evt("chat.rest.request", model=self.config.model, msg_count=len(history) + 1)

            # Utwórz model z system instruction
            model = genai.GenerativeModel(
                model_name=self.config.model,
                system_instruction=self.config.system_prompt,
            )

            # Rozpocznij chat z historią
            chat = model.start_chat(history=history)

            # Wyślij wiadomość
            response = chat.send_message(text)
            text_out = (response.text or "").strip()

            self._evt("chat.rest.ok", chars=len(text_out))
            return text_out
        except Exception as exc:
            self._evt("chat.rest.error", error=str(exc))

            raise ChatError(f"Google Gemini chat completion failed: {exc}") from exc

    async def _ask_openai_stream(self, text: str):
        """
        Asynchroniczne streamujące wywołanie OpenAI Chat Completions.
        Używane w trybie realtime — nie blokuje jak REST.
        Zwraca async generator produkujący fragmenty odpowiedzi.
        """
        # Minimalna walidacja
        if not self.config.model:
            raise ChatError("OpenAI model not configured")
        if not self.config.backend or self.config.backend.lower() != "openai":
            raise ChatError("OpenAI backend not selected")

        # Klucz API
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ChatError("OPENAI_API_KEY is not set")

        try:
            from openai import AsyncOpenAI  # type: ignore
        except Exception as exc:  # pragma: no cover - opcjonalna zależność
            raise ChatError(f"OpenAI SDK unavailable: {exc}") from exc

        client = AsyncOpenAI(api_key=api_key)

        # Zbuduj listę wiadomości (bez nowej wiadomości użytkownika — już jest w historii)
        messages = [{"role": "system", "content": self.config.system_prompt}]
        # weź ostatnie N par z historii (bez ostatniej wiadomości usera dodanej wcześniej)
        max_pairs = max(0, int(self.config.max_history))
        if max_pairs > 0:
            # Użyj wszystkich wiadomości oprócz ostatniej (user message dodanej przed wywołaniem)
            for item in self._history[:-1][-max_pairs * 2 :]:
                messages.append({"role": item.role, "content": item.content})
        # Dodaj aktualną wiadomość użytkownika
        messages.append({"role": "user", "content": text})

        # Payload do API ze streamingiem
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.6,
            "stream": True,
        }
        if self.config.max_tokens is not None:
            payload["max_tokens"] = int(self.config.max_tokens)

        # Wywołanie API (streaming)
        try:
            self._evt("chat.stream.request", model=self.config.model, msg_count=len(messages))
            stream = await client.chat.completions.create(**payload)

            # Iteruj przez fragmenty odpowiedzi
            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta and hasattr(delta, "content") and delta.content:
                        yield delta.content

            self._evt("chat.stream.ok")
        except Exception as exc:
            self._evt("chat.stream.error", error=str(exc))
            raise ChatError(f"OpenAI chat streaming failed: {exc}") from exc

    async def _ask_gemini_stream(self, text: str):
        """
        Asynchroniczne streamujące wywołanie Google Gemini API.
        Używane w trybie realtime — nie blokuje jak REST.
        Zwraca async generator produkujący fragmenty odpowiedzi.
        """
        # Minimalna walidacja
        if not self.config.model:
            raise ChatError("Google model not configured")
        if not self.config.backend or self.config.backend.lower() != "google":
            raise ChatError("Google backend not selected")

        # Klucz API
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise ChatError("GOOGLE_API_KEY is not set")

        try:
            import google.generativeai as genai  # type: ignore
        except Exception as exc:  # pragma: no cover - opcjonalna zależność
            raise ChatError(f"Google Generative AI SDK unavailable: {exc}") from exc

        # Konfiguruj API
        genai.configure(api_key=api_key)

        # Zbuduj historię konwersacji dla Gemini
        # Gemini używa formatu: {'role': 'user'|'model', 'parts': ['text']}
        history = []
        max_pairs = max(0, int(self.config.max_history))
        if max_pairs > 0:
            # Użyj wszystkich wiadomości oprócz ostatniej (user message dodanej przed wywołaniem)
            for item in self._history[:-1][-max_pairs * 2 :]:
                # Mapuj 'assistant' na 'model' dla Gemini
                role = "model" if item.role == "assistant" else item.role
                history.append({"role": role, "parts": [item.content]})

        # Wywołanie API (streaming)
        try:
            self._evt("chat.stream.request", model=self.config.model, msg_count=len(history) + 1)

            # Utwórz model z system instruction
            model = genai.GenerativeModel(
                model_name=self.config.model,
                system_instruction=self.config.system_prompt,
            )

            # Rozpocznij chat z historią
            chat = model.start_chat(history=history)

            # Wyślij wiadomość z streamingiem
            response = await chat.send_message_async(text, stream=True)

            # Iteruj przez fragmenty odpowiedzi
            async for chunk in response:
                if chunk.text:
                    yield chunk.text

            self._evt("chat.stream.ok")
        except Exception as exc:
            self._evt("chat.stream.error", error=str(exc))
            raise ChatError(f"Google Gemini chat streaming failed: {exc}") from exc

    def reset(self) -> None:
        self._history.clear()
