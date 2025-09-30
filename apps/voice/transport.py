"""
WebSocket transport layer for streaming voice service.

Extracted from svc_stream.py (Issue mpieniak01/Rider-Pi#58 - MOVE-FIRST refactoring).
Provides WebSocket connection management, send/recv, graceful close with code=1000,
and reconnection logic with exponential backoff. Uses additional_headers for auth,
ping/pong for heartbeat.

NO API CHANGES - method signatures preserved exactly as in original
StreamingVoiceService.
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
        if not getattr(self, "websocket", None):  # type: ignore[attr-defined]
            return
        await self.websocket.send(data)  # type: ignore[attr-defined]

    async def recv(self) -> str:
        if not getattr(self, "websocket", None):  # type: ignore[attr-defined]
            raise ConnectionError("WebSocket not connected")
        return await self.websocket.recv()  # type: ignore[attr-defined]

    # ────────────────────────────────────────────────────────────────────────
    # aclose() (async) + close() (awaitable) + close_sync() (sync wrapper)
    # ────────────────────────────────────────────────────────────────────────
    async def aclose(self) -> None:
        """Close WebSocket connection gracefully (async)."""
        if getattr(self, "websocket", None):  # type: ignore[attr-defined]
            try:
                self.logger.event(  # type: ignore[attr-defined]
                    "ws.closing",
                    session_id=getattr(self, "session_id", None),  # type: ignore[attr-defined]
                )
                await self.websocket.close(code=1000)  # type: ignore[attr-defined]
                try:
                    await self.websocket.wait_closed()  # type: ignore[attr-defined]
                except Exception:
                    # nie wszystkie implementacje mają wait_closed zgodne z oczekiwaniami
                    pass
                self.logger.event(  # type: ignore[attr-defined]
                    "ws.closed",
                    session_id=getattr(self, "session_id", None),  # type: ignore[attr-defined]
                )
            except Exception as e:
                try:
                    self.logger.event("ws.close_error", error=str(e))  # type: ignore[attr-defined]
                except Exception:
                    pass
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
        """Nawiąż połączenie WS lub zwróć False.

        Kluczowe: używa self._ws_module, jeśli ustawione w orkiestratorze
        (svc_stream). To pozwala testom patchować `apps.voice.svc_stream.websockets`
        i wstrzyknąć mocka. Na porażce czyści stan i awaituje aclose().
        """
        # preferuj moduł wstrzyknięty przez svc_stream; w innym wypadku fallback
        wsmod = getattr(self, "_ws_module", None)
        if wsmod is None:
            wsmod = websockets  # type: ignore

        try:
            api_key = self._get_auth_header()  # type: ignore[attr-defined]

            # Get endpoint from config or environment
            endpoint = (
                self.stream_cfg.endpoint  # type: ignore[attr-defined]
                or os.environ.get("OPENAI_REALTIME_ENDPOINT")
                or ""
            ).strip()
            if not endpoint:
                raise RuntimeError(
                    "Missing realtime endpoint. Set [stream].endpoint in config or OPENAI_REALTIME_ENDPOINT env."
                )

            headers = {"Authorization": f"Bearer {api_key}", "OpenAI-Beta": "realtime=v1"}
            self.logger.event(  # type: ignore[attr-defined]
                "ws.connect_attempt",
                endpoint=mask_secret(endpoint),
            )

            # używamy wsmod.connect (działa z testowym patchem w svc_stream)
            self.websocket = await wsmod.connect(  # type: ignore[attr-defined]
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
            # porażka połączenia – sprzątnij i raportuj
            try:
                self.logger.event("ws.connect_failed", error=str(e))  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                await self.aclose()
            except Exception:
                pass
            self.websocket = None  # type: ignore[attr-defined]
            self.connected = False  # type: ignore[attr-defined]
            try:
                self._publish_error("ws_connect", str(e))  # type: ignore[attr-defined]
            except Exception:
                pass
            return False

    async def _reconnect_loop(self) -> bool:
        """Handle reconnection with exponential backoff."""
        while (  # type: ignore[attr-defined]
            self.retry_count < self.stream_cfg.max_retries and not self.stop_event.is_set()
        ):
            delay_ms = min(  # type: ignore[attr-defined]
                self.stream_cfg.base_ms * (2**self.retry_count),  # type: ignore[attr-defined]
                self.stream_cfg.max_ms,  # type: ignore[attr-defined]
            )
            self.logger.event(  # type: ignore[attr-defined]
                "ws.reconnect_attempt",
                retry=self.retry_count + 1,  # type: ignore[attr-defined]
                delay_ms=delay_ms,
            )
            await asyncio.sleep(delay_ms / 1000.0)

            if await self._connect():
                await self._send_session_update()  # type: ignore[attr-defined]
                return True

            self.retry_count += 1  # type: ignore[attr-defined]

        self.logger.event(  # type: ignore[attr-defined]
            "ws.reconnect_exhausted",
            max_retries=self.stream_cfg.max_retries,  # type: ignore[attr-defined]
        )
        try:
            self._publish_error("ws_connect", "Connection failed after max retries")  # type: ignore[attr-defined]
        except Exception:
            pass
        return False
