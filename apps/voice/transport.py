"""Voice transport (WebSocket)."""

from __future__ import annotations

from typing import Any


class ReconnectingTransport:
    """TODO: extracted from svc_stream.py (WS connect/reconnect/close/wait_closed)."""

    def __init__(self, cfg: dict[str, Any], logger: Any) -> None:
        self.cfg = cfg
        self.logger = logger
