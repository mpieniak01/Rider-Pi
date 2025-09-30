# apps/voice/stream_transport.py
"""WebSocket transport layer for streaming voice service.

Extracted from svc_stream.py to keep files under 600 lines.
Handles WebSocket I/O, reconnection logic, and graceful connection management.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

from . import voice_logging
from .svc_core import mask_secret

# WebSocket library handling with graceful fallback
try:
    import websockets as _websockets  # type: ignore

    websockets = _websockets
except Exception:

    class _WSStub:
        def __getattr__(self, name):
            raise ImportError("websockets library not available")

    websockets = _WSStub()  # type: ignore


class WebSocketTransport:
    """WebSocket transport with connection management and graceful close."""

    def __init__(self, stream_cfg: Any, logger: voice_logging.VoiceLogger):
        self.stream_cfg = stream_cfg
        self.logger = logger
        self.websocket: Any = None
        self.connected = False
        self.retry_count = 0
        self.session_id = ""

    async def send(self, data: str) -> None:
        """Send data to WebSocket."""
        if not self.websocket:
            return
        await self.websocket.send(data)

    async def recv(self) -> str:
        """Receive data from WebSocket."""
        if not self.websocket:
            raise ConnectionError("WebSocket not connected")
        return await self.websocket.recv()

    async def connect(self, api_key: str) -> bool:
        """Establish WebSocket connection."""
        try:
            _ = websockets.connect  # type: ignore[attr-defined]
        except Exception as e:  # pragma: no cover
            raise RuntimeError("websockets library not available. Install with: pip install websockets") from e

        try:
            endpoint = (self.stream_cfg.endpoint or os.environ.get("OPENAI_REALTIME_ENDPOINT") or "").strip()
            if not endpoint:
                raise RuntimeError(
                    "Missing realtime endpoint. Set [stream].endpoint in config or OPENAI_REALTIME_ENDPOINT env."
                )

            headers = {"Authorization": f"Bearer {api_key}", "OpenAI-Beta": "realtime=v1"}
            self.logger.event("ws.connect_attempt", endpoint=mask_secret(endpoint))

            self.websocket = await websockets.connect(  # type: ignore[attr-defined]
                endpoint,
                additional_headers=headers,
                ping_interval=self.stream_cfg.ping_interval_s,
                ping_timeout=10,
            )

            self.connected = True
            self.retry_count = 0
            self.session_id = str(uuid.uuid4())

            self.logger.event("ws.connected", session_id=self.session_id)
            return True

        except Exception as e:
            self.logger.event("ws.connect_failed", error=str(e))
            return False

    async def graceful_close(self) -> None:
        """Close WebSocket connection gracefully with code 1000 and wait for closure."""
        if self.websocket and self.connected:
            try:
                self.logger.event("ws.closing", session_id=self.session_id)
                await self.websocket.close(code=1000)
                await self.websocket.wait_closed()
                self.logger.event("ws.closed", session_id=self.session_id)
            except Exception as e:
                self.logger.event("ws.close_error", error=str(e))
            finally:
                self.websocket = None
                self.connected = False
                self.session_id = ""

    async def reconnect_with_backoff(self, api_key: str) -> bool:
        """Reconnect with exponential backoff."""
        if self.retry_count >= self.stream_cfg.max_retries:
            self.logger.event("ws.max_retries_exceeded")
            return False

        delay_ms = min(
            self.stream_cfg.base_ms * (2**self.retry_count),
            self.stream_cfg.max_ms,
        )
        await asyncio.sleep(delay_ms / 1000.0)
        self.retry_count += 1

        self.logger.event("ws.reconnect_attempt", retry=self.retry_count, delay_ms=delay_ms)
        return await self.connect(api_key)
