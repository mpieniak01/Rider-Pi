"""A bounded BUS event cursor that keeps working when deque entries rotate."""

from __future__ import annotations

from collections.abc import Sequence


class EventCursor:
    """Keep one identity marker; neither deque length nor wall clock is a cursor.

    If the reader falls behind the bounded buffer, deliver the remaining buffer.
    Producer timestamps remain unchanged and consumers can identify stale data.
    """

    def __init__(self) -> None:
        self._last = None

    def drain(self, snapshot: Sequence[dict]) -> list[dict]:
        start = 0
        if self._last is not None:
            for index, value in enumerate(snapshot):
                if value is self._last:
                    start = index + 1
                    break
        rows = list(snapshot[start:])
        if snapshot:
            self._last = snapshot[-1]
        return rows
