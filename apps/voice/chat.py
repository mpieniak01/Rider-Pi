# apps/voice/chat.py
"""Chat backends for conversational responses."""

from __future__ import annotations

import os
import re  # <-- IMPORT RE
from dataclasses import dataclass
from typing import Any

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

    # LOCAL HTTP (prosty REST: POST JSON -> JSON)
    base_url: str | None = None  # np. "[http://127.0.0.1:8092](http://127.0.0.1:8092)"
    endpoint: str | None = None  # np. "/api/chat"
    timeout: float | None = None  # sekundy


@dataclass
class Message:
    role: str
    content: str


# === POCZĄTEK POPRAWKI: Funkcja czyszcząca Markdown ===
_MARKDOWN_CLEANER = re.compile(r"[`*#_~]")


def _clean_markdown(text: str) -> str:
    """
    Usuwa podstawowe znaki formatujące markdown (jak ```, *, _, #),
    które mogą być zwracane przez modele Gemini i powodować błędy TTS.
    """
    if not text:
        return ""
    # Usuń bloki kodu i inne znaki specjalne
    return _MARKDOWN_CLEANER.sub("", text).strip()


# === KONIEC POPRAWKI ===


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

    def _history_pairs_limit(self) -> int:
        max_pairs = max(0, int(self.config.max_history))
        return max_pairs

    def _clip_history(self) -> None:
        max_pairs = self._history_pairs_limit()
        if max_pairs > 0 and len(self._history) > max_pairs * 2:
            self._history = self._history[-max_pairs * 2 :]

    def _build_messages_openai(self, user_text: str) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [{"role": "system", "content": self.config.system_prompt}]
        max_pairs = self._history_pairs_limit()
        if max_pairs > 0:
            for item in self._history[-max_pairs * 2 :]:
                messages.append({"role": item.role, "content": item.content})
        messages.append({"role": "user", "content": user_text})
        return messages

    def _build_history_gemini(self) -> list[dict[str, list[str]]]:
        history: list[dict[str, list[str]]] = []
        max_pairs = self._history_pairs_limit()
        if max_pairs > 0:
            for item in self._history[-max_pairs * 2 :]:
                role = "model" if item.role == "assistant" else item.role
                history.append({"role": role, "parts": [item.content]})
        return history

    def _build_messages_local(self, user_text: str) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [{"role": "system", "content": self.config.system_prompt}]
        max_pairs = self._history_pairs_limit()
        if max_pairs > 0:
            for item in self._history[-max_pairs * 2 :]:
                messages.append({"role": item.role, "content": item.content})
        messages.append({"role": "user", "content": user_text})
        return messages

    def ask(self, text: str) -> tuple[str, list[Message]]:
        backend = (self.config.backend or "echo").lower()

        # === POCZĄTEK POPRAWKI: Czyszczenie tekstu wejściowego ===
        # Czyścimy tekst, który mógł przyjść z ASR z markdownem
        cleaned_text = _clean_markdown(text)
        # === KONIEC POPRAWKI ===

        if backend == "openai":
            reply = self._ask_openai(cleaned_text)  # Użyj cleaned_text
        elif backend == "google":
            reply = self._ask_gemini(cleaned_text)  # Użyj cleaned_text
        elif backend == "local":
            reply = self._ask_local_http(cleaned_text)  # Użyj cleaned_text
        else:
            # Prosty backend echa – przydatny offline/testowo
            reply = f"You said: {cleaned_text.strip()}"  # Użyj cleaned_text

        # === POCZĄTEK POPRAWKI: Czyszczenie tekstu wyjściowego ===
        # Czyścimy odpowiedź *przed* zapisaniem jej w historii i odesłaniem
        cleaned_reply = _clean_markdown(reply)
        # === KONIEC POPRAWKI ===

        # aktualizuj historię (user + assistant)
        self._history.append(Message(role="user", content=cleaned_text))  # Użyj cleaned_text
        self._history.append(Message(role="assistant", content=cleaned_reply))  # Użyj cleaned_reply

        # ogranicz rozmiar historii (pary user/assistant)
        self._clip_history()

        return cleaned_reply, list(self._history)  # Zwróć cleaned_reply

    async def ask_stream(self, text: str):
        """
        Asynchroniczne wywołanie chat completions ze streamingiem.
        Zwraca async generator produkujący fragmenty (tokeny) odpowiedzi.
        Używane typowo przy transport="realtime".
        """
        backend = (self.config.backend or "echo").lower()

        # === POCZĄTEK POPRAWKI: Czyszczenie tekstu wejściowego ===
        cleaned_text = _clean_markdown(text)
        # === KONIEC POPRAWKI ===

        # Dodaj wiadomość użytkownika do historii
        self._history.append(Message(role="user", content=cleaned_text))

        if backend == "openai":
            # Streamujące wywołanie OpenAI
            full_reply = ""
            async for chunk in self._ask_openai_stream(cleaned_text):  # Użyj cleaned_text
                full_reply += chunk
                yield chunk
            self._history.append(Message(role="assistant", content=_clean_markdown(full_reply)))  # Zapisz wyczyszczoną

        elif backend == "google":
            # Quasi-streaming dla Google Gemini
            full_reply = ""
            async for chunk in self._ask_gemini_stream(cleaned_text):  # Użyj cleaned_text
                full_reply += chunk
                yield chunk
            self._history.append(Message(role="assistant", content=_clean_markdown(full_reply)))  # Zapisz wyczyszczoną

        elif backend == "local":
            # Brak natywnego streamu — wykonaj pojedyncze wywołanie i zwróć jednorazowy chunk
            reply = self._ask_local_http(cleaned_text, realtime_guard=False)  # Użyj cleaned_text
            cleaned_reply = _clean_markdown(reply)  # Wyczyść odpowiedź
            self._history.append(Message(role="assistant", content=cleaned_reply))
            yield cleaned_reply

        else:
            # Echo backend — zwróć od razu całą odpowiedź
            reply = f"You said: {cleaned_text.strip()}"  # Użyj cleaned_text
            self._history.append(Message(role="assistant", content=reply))
            yield reply

        # Ogranicz rozmiar historii (po dodaniu odpowiedzi)
        self._clip_history()

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

        messages = self._build_messages_openai(text)

        payload: dict[str, Any] = {
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

            # === POCZĄTEK POPRAWKI: Czyszczenie odpowiedzi ===
            cleaned_text_out = _clean_markdown(text_out)
            self._evt("chat.rest.ok", chars=len(cleaned_text_out), raw_chars=len(text_out))
            return cleaned_text_out
            # === KONIEC POPRAWKI ===

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
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ChatError("GOOGLE_API_KEY is not set")

        try:
            import google.generativeai as genai  # type: ignore
        except Exception as exc:  # pragma: no cover - opcjonalna zależność
            raise ChatError(f"Google Generative AI SDK unavailable: {exc}") from exc

        # Konfiguruj API
        genai.configure(api_key=api_key)

        history = self._build_history_gemini()

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

            # === POCZĄTEK POPRAWKI: Czyszczenie odpowiedzi ===
            cleaned_text_out = _clean_markdown(text_out)
            self._evt("chat.rest.ok", chars=len(cleaned_text_out), raw_chars=len(text_out))
            return cleaned_text_out
            # === KONIEC POPRAWKI ===

        except Exception as exc:
            self._evt("chat.rest.error", error=str(exc))
            raise ChatError(f"Google Gemini chat completion failed: {exc}") from exc

    def _ask_local_http(self, text: str, *, realtime_guard: bool = True) -> str:
        """
        Prosty backend HTTP:
          POST {base_url}{endpoint}
          JSON payload: {"messages":[{"role":"system","content":"..."},...,{"role":"user","content":"..."}]}
          Response: {"text":"..."} lub {"message":{"content":"..."}}
        """
        if realtime_guard and (self.config.transport or "").lower() == "realtime":
            raise ChatError("Chat REST disabled when transport=realtime")

        try:
            import requests  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise ChatError(f"requests not available: {exc}") from exc

        base_url = (self.config.base_url or "").rstrip("/")
        endpoint = self.config.endpoint or "/api/chat"
        url = f"{base_url}{endpoint}"
        timeout = self.config.timeout or 10.0

        messages = self._build_messages_local(text)
        payload = {"messages": messages}
        self._evt("chat.local.request", url=url, msg_count=len(messages))

        try:
            resp = requests.post(url, json=payload, timeout=timeout)
        except Exception as exc:
            self._evt("chat.local.error", error=str(exc))
            raise ChatError(f"LOCAL CHAT: request failed: {exc}") from exc

        if resp.status_code >= 400:
            snippet = (resp.text or "")[:200]
            self._evt("chat.local.http_error", status=resp.status_code, body=snippet)
            raise ChatError(f"LOCAL CHAT HTTP {resp.status_code}: {snippet}")

        try:
            data = resp.json()
        except Exception as e:
            raise ChatError("LOCAL CHAT: invalid JSON") from e

        text_out = ((data.get("text") or "") or ((data.get("message") or {}).get("content") or "")).strip()

        if not text_out:
            raise ChatError("LOCAL CHAT: empty response")

        # === POCZĄTEK POPRAWKI: Czyszczenie odpowiedzi ===
        cleaned_text_out = _clean_markdown(text_out)
        self._evt("chat.local.ok", chars=len(cleaned_text_out), raw_chars=len(text_out))
        return cleaned_text_out
        # === KONIEC POPRAWKI ===

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
        max_pairs = self._history_pairs_limit()
        if max_pairs > 0:
            for item in self._history[:-1][-max_pairs * 2 :]:
                messages.append({"role": item.role, "content": item.content})
        messages.append({"role": "user", "content": text})

        payload: dict[str, Any] = {
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
                        # === POCZĄTEK POPRAWKI: Czyszczenie strumienia ===
                        # Czyścimy na bieżąco, ale to może być ryzykowne
                        # Lepsza strategia: czyścić całą odpowiedź na końcu
                        yield delta.content
                        # === KONIEC POPRAWKI ===

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
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ChatError("GOOGLE_API_KEY is not set")

        try:
            import google.generativeai as genai  # type: ignore
        except Exception as exc:  # pragma: no cover - opcjonalna zależność
            raise ChatError(f"Google Generative AI SDK unavailable: {exc}") from exc

        # Konfiguruj API
        genai.configure(api_key=api_key)

        history = []
        max_pairs = self._history_pairs_limit()
        if max_pairs > 0:
            for item in self._history[:-1][-max_pairs * 2 :]:
                role = "model" if item.role == "assistant" else item.role
                history.append({"role": role, "parts": [item.content]})

        # Wywołanie API (streaming)
        try:
            self._evt(
                "chat.stream.request",
                model=self.config.model,
                msg_count=len(history) + 1,
            )

            model = genai.GenerativeModel(
                model_name=self.config.model,
                system_instruction=self.config.system_prompt,
            )
            chat = model.start_chat(history=history)

            response = await chat.send_message_async(text, stream=True)

            async for chunk in response:
                if chunk.text:
                    # === POCZĄTEK POPRAWKI: Czyszczenie strumienia ===
                    # Czyścimy na bieżąco, ale to może być ryzykowne
                    # Lepsza strategia: czyścić całą odpowiedź na końcu
                    yield chunk.text
                    # === KONIEC POPRAWKI ===

            self._evt("chat.stream.ok")
        except Exception as exc:
            self._evt("chat.stream.error", error=str(exc))
            raise ChatError(f"Google Gemini chat streaming failed: {exc}") from exc

    def reset(self) -> None:
        self._history.clear()
