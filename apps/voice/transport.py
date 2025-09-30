"""WebSocket transport layer for streaming voice service.

Extracted from svc_stream.py (Issue mpieniak01/Rider-Pi#58 - MOVE-FIRST refactoring).
Provides WebSocket connection management, send/recv, graceful close with code=1000,
and reconnection logic with exponential backoff. Uses additional_headers for auth,
ping/pong for heartbeat.

NO API CHANGES - methods signatures preserved exactly as in original StreamingVoiceService.
"""

from __future__ import annotations

import asyncio
import os
import uuid

try:
    import websockets  # type: ignore
except Exception:  # pragma: no cover

    class _WSStub:
        def __getattr__(self, _):  # minimalny stub dla testów
            raise RuntimeError("websockets unavailable")

    websockets = _WSStub()  # type: ignore

from .svc_core import mask_secret


class StreamingVoiceTransportMixin:
    """WebSocket transport methods (extracted from StreamingVoiceService).

    This mixin provides the exact transport-layer methods that were in
    StreamingVoiceService, extracted via MOVE-FIRST approach.
    Expects parent class to have: websocket, session_id, connected, logger,
    stream_cfg, retry_count, stop_event, _get_auth_header(), _publish_error(),
    _send_session_update().
    """

    # ---- small async wrappers (ułatwiają mocki/testy) ----
    async def send(self, data: str) -> None:
        if not self.websocket:  # type: ignore[attr-defined]
            return
        await self.websocket.send(data)  # type: ignore[attr-defined]

    async def recv(self) -> str:
        if not self.websocket:  # type: ignore[attr-defined]
            raise ConnectionError("WebSocket not connected")
        return await self.websocket.recv()  # type: ignore[attr-defined]

    # ──────────────────────────────────────────────────────────────────────────
    # ZAMIANA: aclose() (async) + close() (sync wrapper) zamiast samego async close()
    # ──────────────────────────────────────────────────────────────────────────
    async def aclose(self) -> None:
        """Close WebSocket connection gracefully (async)."""
        if self.websocket:  # type: ignore[attr-defined]
            try:
                self.logger.event("ws.closing", session_id=self.session_id)  # type: ignore[attr-defined]
                await self.websocket.close(code=1000)  # type: ignore[attr-defined]
                await self.websocket.wait_closed()  # type: ignore[attr-defined]
                self.logger.event("ws.closed", session_id=self.session_id)  # type: ignore[attr-defined]
            except Exception as e:
                self.logger.event("ws.close_error", error=str(e))  # type: ignore[attr-defined]
            finally:
                self.websocket = None  # type: ignore[attr-defined]
                self.connected = False  # type: ignore[attr-defined]

    async def close(self) -> None:
        """Async close – zgodne z oczekiwaniami testów (awaitable)."""
        await self.aclose()

    def close_sync(self) -> None:
        """Sync wrapper – do użycia z kodu niesynchronicznego (CLI, sygnały)."""
        try:
            from .utils import run_sync

            run_sync(self.aclose())
        except Exception as e:
            try:
                self.logger.event("ws.close_sync_error", error=str(e))  # type: ignore[attr-defined]
            except Exception:
                pass

    async def _connect(self) -> bool:
        try:
            _ = websockets.connect  # type: ignore[attr-defined]
        except Exception as e:  # pragma: no cover
            raise RuntimeError("websockets library not available. Install with: pip install websockets") from e

        try:
            api_key = self._get_auth_header()  # type: ignore[attr-defined]
            # Get endpoint from config or environment
            endpoint = (
                # type: ignore[attr-defined]
                self.stream_cfg.endpoint or os.environ.get("OPENAI_REALTIME_ENDPOINT") or ""
            ).strip()
            if not endpoint:
                raise RuntimeError(
                    "Missing realtime endpoint. Set [stream].endpoint in config or OPENAI_REALTIME_ENDPOINT env."
                )

            headers = {"Authorization": f"Bearer {api_key}", "OpenAI-Beta": "realtime=v1"}
            self.logger.event("ws.connect_attempt", endpoint=mask_secret(endpoint))  # type: ignore[attr-defined]

            self.websocket = await websockets.connect(  # type: ignore[attr-defined]
                endpoint,
                additional_headers=headers,
                ping_interval=self.stream_cfg.ping_interval_s,  # type: ignore[attr-defined]
                ping_timeout=10,
            )

            self.connected = True  # type: ignore[attr-defined]
            self.retry_count = 0  # type: ignore[attr-defined]
            self.session_id = str(uuid.uuid4())  # type: ignore[attr-defined]

            self.logger.event("ws.connected", session_id=self.session_id)  # type: ignore[attr-defined]
            return True

        except Exception as e:
            self.logger.event("ws.connect_failed", error=str(e))  # type: ignore[attr-defined]
            self._publish_error("ws_connect", str(e))  # type: ignore[attr-defined]
            return False

    async def _reconnect_loop(self) -> bool:
        """Handle reconnection with exponential backoff."""
        # type: ignore[attr-defined]
        while self.retry_count < self.stream_cfg.max_retries and not self.stop_event.is_set():  # type: ignore
            # type: ignore[attr-defined]
            delay_ms = min(
                self.stream_cfg.base_ms * (2**self.retry_count),
                self.stream_cfg.max_ms,  # type: ignore[attr-defined]
            )
            # type: ignore[attr-defined]
            self.logger.event(
                "ws.reconnect_attempt",
                retry=self.retry_count + 1,
                delay_ms=delay_ms,  # type: ignore[attr-defined]
            )
            await asyncio.sleep(delay_ms / 1000.0)

            if await self._connect():
                await self._send_session_update()  # type: ignore[attr-defined]
                return True

            self.retry_count += 1  # type: ignore[attr-defined]

        # type: ignore[attr-defined]
        self.logger.event(
            "ws.reconnect_exhausted",
            max_retries=self.stream_cfg.max_retries,  # type: ignore[attr-defined]
        )
        self._publish_error("ws_connect", "Connection failed after max retries")  # type: ignore[attr-defined]
        return False
