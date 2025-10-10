# apps/voice/transport.py
""" "WebSocket transport layer for Rider-Pi voice streaming.

Provides clean WebSocket connection management with:
- Proper connection lifecycle (connect, send, recv, close)
- Heartbeat/ping handling
- Reconnection logic
- Clean shutdown with code 1000

Compat shims:
- StreamingVoiceTransportMixin: legacy no-op mixin kept for import compatibility.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

from . import voice_logging
from .errors import StreamError

# ---- Preferred async library: websockets ------------------------------------
_ws_async = None
try:
    import websockets as _ws_async  # type: ignore
except Exception:
    _ws_async = None

# ---- Fallback sync library: websocket-client --------------------------------
_ws_sync = None
try:
    import websocket as _ws_sync  # type: ignore  # pip install websocket-client
except Exception:
    _ws_sync = None


class WebSocketTransport:
    """WebSocket transport with connection management and heartbeat.

    Supports:
      - websockets (async, preferred)
      - websocket-client (sync, fallback via to_thread)
    """

    def __init__(
        self,
        endpoint: str,
        auth_header: str,
        ping_interval_s: int = 10,
        logger: voice_logging.VoiceLogger | None = None,
    ):
        self.endpoint = endpoint
        self.auth_header = auth_header
        self.ping_interval_s = ping_interval_s

        if logger is None:
            from .common import ensure_event_logger

            logger = ensure_event_logger(voice_logging.get_logger(__name__))
        self.logger = logger

        # Library mode flags
        self._use_async = _ws_async is not None
        self._use_sync = (not self._use_async) and (_ws_sync is not None)

        if not self._use_async and not self._use_sync:
            raise ImportError("No WebSocket library available. Install 'websockets' or 'websocket-client'.")

        # Connection state
        self.websocket: Any = None  # websockets.client.WebSocketClientProtocol or _ws_sync.WebSocket
        self.session_id: str = ""
        self.connected: bool = False
        self.retry_count: int = 0

        # Heartbeat
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._stop_heartbeat = False

    async def connect(self, *, max_retries: int = 3) -> bool:
        """Connect to WebSocket endpoint."""
        for attempt in range(max_retries + 1):
            try:
                effective_endpoint = os.environ.get("OPENAI_REALTIME_ENDPOINT") or self.endpoint
                if not effective_endpoint:
                    self.logger.event("ws.connect.no_endpoint")
                    return False

                self.logger.event(
                    "ws.connect.attempt",
                    endpoint=self._mask_endpoint(effective_endpoint),
                    attempt=attempt + 1,
                )

                if self._use_async:
                    # --- websockets (async) ---
                    headers = []
                    if self.auth_header:
                        headers.append(("Authorization", self.auth_header))
                    headers.append(("OpenAI-Beta", "realtime=v1"))

                    self.websocket = await _ws_async.connect(  # type: ignore[attr-defined]
                        effective_endpoint,
                        extra_headers=headers,
                        ping_interval=self.ping_interval_s,
                        ping_timeout=10,
                    )
                    self.logger.event("ws.library", name="websockets")
                else:
                    # --- websocket-client (sync) ---
                    hdr_list: list[str] = []
                    if self.auth_header:
                        hdr_list.append(f"Authorization: {self.auth_header}")
                    hdr_list.append("OpenAI-Beta: realtime=v1")

                    # create_connection jest blokujące → uruchom w wątku
                    self.websocket = await asyncio.to_thread(
                        _ws_sync.create_connection,  # type: ignore[attr-defined]
                        effective_endpoint,
                        header=hdr_list,  # ✔️ poprawnie: header=..., NIE extra_headers
                        timeout=10,
                    )
                    self.logger.event("ws.library", name="websocket-client")

                self.connected = True
                self.retry_count = 0
                self.session_id = str(uuid.uuid4())

                # Start heartbeat
                self._stop_heartbeat = False
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

                self.logger.event("ws.connected", session_id=self.session_id)
                return True

            except Exception as e:
                self.logger.event("ws.connect_failed", error=str(e), attempt=attempt + 1)
                if attempt < max_retries:
                    await asyncio.sleep(min(2**attempt, 10))  # Exponential backoff

        return False

    async def send(self, data: str) -> None:
        """Send data through WebSocket."""
        if not self.websocket or not self.connected:
            raise StreamError("WebSocket not connected")

        try:
            if self._use_async:
                await self.websocket.send(data)
            else:
                await asyncio.to_thread(self.websocket.send, data)
        except Exception as e:
            self.connected = False
            raise StreamError(f"WebSocket send failed: {e}") from e

    async def recv(self) -> str:
        """Receive data from WebSocket."""
        if not self.websocket or not self.connected:
            raise StreamError("WebSocket not connected")

        try:
            if self._use_async:
                message = await self.websocket.recv()
            else:
                message = await asyncio.to_thread(self.websocket.recv)
            return str(message)
        except Exception as e:
            self.connected = False
            raise StreamError(f"WebSocket recv failed: {e}") from e

    async def close(self) -> None:
        """Close WebSocket connection cleanly."""
        # Stop heartbeat first
        self._stop_heartbeat = True
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        if self.websocket and self.connected:
            try:
                self.logger.event("ws.closing", session_id=self.session_id)

                if self._use_async:
                    await self.websocket.close(code=1000)
                    await self.websocket.wait_closed()
                else:
                    # websocket-client close
                    await asyncio.to_thread(self.websocket.close, status=1000)

                self.logger.event("ws.closed", session_id=self.session_id)
            except Exception as e:
                self.logger.event("ws.close_error", error=str(e))
            finally:
                self.websocket = None
                self.connected = False
                self.session_id = ""

    async def _heartbeat_loop(self) -> None:
        """Heartbeat loop to keep connection alive."""
        while not self._stop_heartbeat and self.connected:
            try:
                await asyncio.sleep(self.ping_interval_s)

                if self._stop_heartbeat or not self.connected:
                    break

                # For async websockets, ping is handled by library (ping_interval).
                # For websocket-client, send manual ping.
                if (not self._use_async) and self.websocket:
                    try:
                        await asyncio.to_thread(self.websocket.ping)
                    except Exception:
                        self.connected = False
                        self.logger.event("ws.heartbeat.ping_failed")
                        break

                if self._use_async and self.websocket and self.websocket.closed:
                    self.logger.event("ws.heartbeat.connection_closed")
                    self.connected = False
                    break

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.event("ws.heartbeat.error", error=str(e))
                self.connected = False
                break

    def _mask_endpoint(self, endpoint: str) -> str:
        if not endpoint:
            return "not configured"
        return endpoint.replace("model=", "model=***")


class ReconnectingTransport:
    """WebSocket transport with automatic reconnection."""

    def __init__(
        self,
        endpoint: str,
        auth_header: str,
        max_retries: int = 6,
        base_ms: int = 250,
        max_ms: int = 5000,
        ping_interval_s: int = 10,
        logger: voice_logging.VoiceLogger | None = None,
    ):
        self.endpoint = endpoint
        self.auth_header = auth_header
        self.max_retries = max_retries
        self.base_ms = base_ms
        self.max_ms = max_ms
        self.ping_interval_s = ping_interval_s
        if logger is None:
            from .common import ensure_event_logger

            logger = ensure_event_logger(voice_logging.get_logger(__name__))
        self.logger = logger

        self.transport: WebSocketTransport | None = None
        self.retry_count = 0

    async def ensure_connected(self) -> bool:
        """Ensure WebSocket connection is established."""
        if self.transport and self.transport.connected:
            return True
        return await self._reconnect()

    async def _reconnect(self) -> bool:
        """Attempt to reconnect with exponential backoff."""
        while self.retry_count < self.max_retries:
            if self.transport:
                await self.transport.close()

            self.transport = WebSocketTransport(self.endpoint, self.auth_header, self.ping_interval_s, self.logger)

            delay_ms = min(self.base_ms * (2**self.retry_count), self.max_ms)

            if self.retry_count > 0:
                self.logger.event("ws.reconnect.delay", delay_ms=delay_ms, retry=self.retry_count)
                await asyncio.sleep(delay_ms / 1000.0)

            if await self.transport.connect():
                self.retry_count = 0
                return True

            self.retry_count += 1
            self.logger.event("ws.reconnect.failed", retry=self.retry_count, max_retries=self.max_retries)

        self.logger.event("ws.reconnect.exhausted", max_retries=self.max_retries)
        return False

    async def send(self, data: str) -> None:
        """Send data, reconnecting if needed."""
        if not await self.ensure_connected():
            raise StreamError("Cannot establish WebSocket connection")
        await self.transport.send(data)

    async def recv(self) -> str:
        """Receive data, reconnecting if needed."""
        if not await self.ensure_connected():
            raise StreamError("Cannot establish WebSocket connection")
        return await self.transport.recv()

    async def close(self) -> None:
        """Close transport connection."""
        if self.transport:
            await self.transport.close()
            self.transport = None
        self.retry_count = 0


# ─────────────────────────────────────────────────────────────────────────────
# Legacy compatibility shim
class StreamingVoiceTransportMixin:
    """Deprecated legacy mixin.

    Zostawiony tylko po to, aby `from .transport import StreamingVoiceTransportMixin`
    nie wywalał ImportError. Nie wnosi żadnych metod – dawny kod i tak używa
    faktycznego transportu przez ReconnectingTransport/WebSocketTransport.
    """

    pass


__all__ = [
    "WebSocketTransport",
    "ReconnectingTransport",
    "StreamingVoiceTransportMixin",  # compat
]
