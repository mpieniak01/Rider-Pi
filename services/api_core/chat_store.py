from __future__ import annotations
from collections import deque
from threading import Lock
import time
from typing import Dict, List

class ChatStore:
    def __init__(self, maxlen: int = 1000) -> None:
        self._q: deque[Dict[str, object]] = deque(maxlen=maxlen)
        self._lock = Lock()

    def add(self, msg: str, user: str) -> Dict[str, object]:
        item = {"ts": time.time(), "user": user, "msg": msg}
        with self._lock:
            self._q.append(item)
        return item

    def list(self, limit: int = 20, newest_first: bool = True) -> List[Dict[str, object]]:
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
