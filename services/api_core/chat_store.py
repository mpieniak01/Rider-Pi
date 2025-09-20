from __future__ import annotations

import builtins
import time
from collections import deque
from threading import Lock


class ChatStore:
    def __init__(self, maxlen: int = 1000) -> None:
        self._q: deque[dict[str, object]] = deque(maxlen=maxlen)
        self._lock = Lock()

    def add(self, msg: str, user: str) -> dict[str, object]:
        item = {"ts": time.time(), "user": user, "msg": msg}
        with self._lock:
            self._q.append(item)
        return item

    def list(self, limit: int = 20, newest_first: bool = True) -> builtins.list[dict[str, object]]:
        if limit <= 0:
            return []
        with self._lock:
            data = list(self._q)[-limit:]
        if newest_first:
            data.reverse()
        return data


_STORE: ChatStore | None = None


def get_store() -> ChatStore:
    global _STORE
    if _STORE is None:
        _STORE = ChatStore(maxlen=1000)
    return _STORE
