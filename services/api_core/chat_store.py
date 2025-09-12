from __future__ import annotations

from collections import deque
from typing import Any

_BUF: deque[dict[str, Any]] = deque(maxlen=1000)


def append_msg(rec: dict[str, Any]) -> None:
    """Append a chat record."""
    _BUF.append(rec)


def tail(n: int) -> list[dict[str, Any]]:
    """Return the last n records."""
    n = max(0, min(n, len(_BUF)))
    return list(_BUF)[-n:]
