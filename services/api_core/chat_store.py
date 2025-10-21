# services/api_core/chat_store.py
from __future__ import annotations

import time
from collections import deque
from collections.abc import Iterable
from threading import Lock
from typing import Any


class ChatStore:
    """Prosty, wątkowo-bezpieczny magazyn wiadomości czatu (FIFO z maxlen)."""

    def __init__(self, maxlen: int = 1000) -> None:
        self._q: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = Lock()

    # ── API kanoniczne ────────────────────────────────────────────────────────
    def add(self, msg: str, user: str) -> dict[str, Any]:
        """Dodaj wiadomość w formie pól msg/user (czas zostanie nadany)."""
        item: dict[str, Any] = {"ts": time.time(), "user": user, "msg": msg}
        with self._lock:
            self._q.append(item)
        return item

    def add_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Dodaj już przygotowany rekord (z normalizacją minimalną)."""
        norm: dict[str, Any] = dict(item)
        if "ts" not in norm:
            norm["ts"] = time.time()
        if "user" not in norm:
            norm["user"] = "user"
        if "msg" not in norm:
            norm["msg"] = ""
        with self._lock:
            self._q.append(norm)
        return norm

    def list(self, limit: int | None = 20, newest_first: bool = True) -> list[dict[str, Any]]:
        """
        Zwróć listę elementów. Gdy limit=None lub limit<=0 → zwróć wszystkie.
        newest_first=True domyślnie odwraca kolejność (najnowsze na górze),
        co jest zgodne z dotychczasowym zachowaniem tego modułu.
        """
        with self._lock:
            data_all = list(self._q)

        if limit is None or limit <= 0:
            data = data_all
        else:
            data = data_all[-limit:]

        if newest_first:
            data.reverse()
        return data

    # ── Syntactic sugar ───────────────────────────────────────────────────────
    def __len__(self) -> int:  # pomocne w diagnostyce/testach
        with self._lock:
            return len(self._q)


# ── Singleton modułowy ───────────────────────────────────────────────────────
_STORE: ChatStore | None = None


def get_store() -> ChatStore:
    global _STORE
    if _STORE is None:
        _STORE = ChatStore(maxlen=1000)
    return _STORE


# ── Wrappery kompatybilności (oczekiwane przez chat_glue itp.) ──────────────
def append(item: dict[str, Any]) -> dict[str, Any]:
    """Dodaj element przez prosty append(dict)."""
    return get_store().add_item(item)


def add(item: dict[str, Any]) -> dict[str, Any]:
    """Zachowujemy też nazwę 'add' przyjmującą dict (część klejów tak woła)."""
    return get_store().add_item(item)


def history(limit: int | None = None) -> Iterable[dict[str, Any]]:
    """Zwraca historię jako iterowalną listę dictów (starsze→nowsze)."""
    # wiele UI/API oczekuje kolejności „od najstarszej”, więc newest_first=False
    return get_store().list(limit=limit, newest_first=False)
