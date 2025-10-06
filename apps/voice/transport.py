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
import json
import os
import uuid
from typing import Any

try:
    import websockets  # type: ignore
    from websockets.exceptions import ConnectionClosed, ConnectionClosedError  # type: ignore
except Exception:  # pragma: no cover

    class _WSStub:
        def __getattr__(self, _):  # minimalny stub dla testów
            raise RuntimeError("websockets unavailable")

    websockets = _WSStub()  # type: ignore
    ConnectionClosed = Exception  # type: ignore
    ConnectionClosedError = Exception  # type: ignore

from .svc_core import mask_secret


def _env_flag(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip() in ("1", "true", "True", "YES", "yes")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except Exception:
        return default


class StreamingVoiceTransportMixin:
    """WebSocket transport methods (extracted from StreamingVoiceService).

    This mixin provides the exact transport-layer methods that were in
    StreamingVoiceService, extracted via MOVE-FIRST approach.
    Expects parent class to have: websocket, session_id, connected, logger,
    stream_cfg, retry_count, stop_event, _get_auth_header(), _publish_error(),
    _send_session_update().
    """

    # ───── internal, low-cost logging helpers (opt-in) ─────

    def _wslog_enabled(self) -> bool:
        # Domyślnie wyłączone; włącz LOG-iem środowiskowym
        return _env_flag("VOICE_WS_LOG", False)

    def _wsdump_enabled(self) -> bool:
        return _env_flag("VOICE_WS_DUMP", False)

    def _append_sample_every(self) -> int:
        # Co ile append-ów logować (i opcjonalnie dumpować). 50 =~ 1 s przy 20 ms.
        return max(1, _env_int("VOICE_WS_APPEND_SAMPLE_EVERY", 50))

    def _ws_send_counter_inc(self) -> int:
        cnt = getattr(self, "_ws_send_counter", 0) + 1
        self._ws_send_counter = cnt
        return cnt

    def _should_log_type(self, t: str | None, is_send: bool, ordinal: int) -> bool:
        if not t:
            return False
        # Nie loguj każdej próbki audio; tylko co N-ty pakiet
        if t == "input_audio_buffer.append":
            return ordinal % self._append_sample_every() == 0
        # Loguj commit/response/session/error normalnie
        if t.startswith("response.") or t in (
            "input_audio_buffer.commit",
            "response.create",
            "session.update",
            "session.updated",
            "error",
            "rate_limits.updated",
        ):
            return True
        # Reszta na DEBUG – ale my nie spamujemy; zostawiamy ciszę
        return False

    def _ws_try_get_type(self, payload: str) -> str | None:
        try:
            obj = json.loads(payload)
            t = obj.get("type")
            if isinstance(t, str):
                return t
        except Exception:
            return None
        return None

    def _ws_dump(self, fname: str, payload: str) -> None:
        if not self._wsdump_enabled():
            return
        try:
            from datetime import datetime

            ts = datetime.utcnow().isoformat() + "Z"
            with open(fname, "a", encoding="utf-8") as f:
                f.write(f"{ts} {payload}\n")
        except Exception:
            # dump jest opcjonalny – nigdy nie przerywamy ścieżki
            pass

    # ---- small async wrappers (ułatwiają mocki/testy) ----
    async def send(self, data: str) -> None:
        if not getattr(self, "websocket", None):  # type: ignore[attr-defined]
            return

        # lekka inspekcja typu (bezpieczna, nie wymaga pełnego JSON na INFO)
        t = self._ws_try_get_type(data)
        ordinal = self._ws_send_counter_inc()

        if self._wslog_enabled() and self._should_log_type(t, True, ordinal):
            try:
                self.logger.event(  # type: ignore[attr-defined]
                    "ws.send",
                    t=t or "<unknown>",
                    size=len(data),
                    ordinal=ordinal,
                )
            except Exception:
                pass

        if self._wsdump_enabled() and self._should_log_type(t, True, ordinal):
            self._ws_dump("/tmp/voice-ws-send.jsonl", data)

        await self.websocket.send(data)  # type: ignore[attr-defined]

    async def recv(self) -> str:
        if not getattr(self, "websocket", None):  # type: ignore[attr-defined]
            raise ConnectionError("WebSocket not connected")

        try:
            msg = await self.websocket.recv()  # type: ignore[attr-defined]
        except (ConnectionClosed, ConnectionClosedError) as e:
            # Zsynchronizuj stan i rzuć dalej – wyżej zadziała reconnect/backoff
            self.connected = False  # type: ignore[attr-defined]
            try:
                self.logger.event("ws.recv_closed", reason=str(e))  # type: ignore[attr-defined]
            except Exception:
                pass
            raise

        if not self._wslog_enabled() and not self._wsdump_enabled():
            return msg

        # Staramy się logować tylko rzeczy wartościowe
        t: str | None = None
        s: str
        if isinstance(msg, (bytes, bytearray)):
            # Realtime zwraca JSON – jeśli kiedyś pojawi się binarny, nie spamujemy
            s = ""
        else:
            s = msg
            t = self._ws_try_get_type(s)

        if (
            self._wslog_enabled()
            and t
            and (t.startswith("response.") or t in ("error", "rate_limits.updated", "session.updated"))
        ):
            try:
                self.logger.event("ws.recv", t=t)  # type: ignore[attr-defined]
            except Exception:
                pass

        if (
            self._wsdump_enabled()
            and t
            and (t.startswith("response.") or t in ("error", "rate_limits.updated", "session.updated"))
        ):
            self._ws_dump("/tmp/voice-ws-recv.jsonl", s)

        return msg

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

            headers = {
                "Authorization": f"Bearer {api_key}",
                "OpenAI-Beta": "realtime=v1",
            }
            self.logger.event(  # type: ignore[attr-defined]
                "ws.connect_attempt",
                endpoint=mask_secret(endpoint),
            )

            # Standardowe parametry połączenia pod realtime audio:
            # - extra_headers (fallback z additional_headers dla kompatybilności),
            # - max_size=None (duże ramki, brak limitu),
            # - compression=None (mniejsze opóźnienia),
            # - ping_interval/ping_timeout (utrzymanie sesji).
            connect_kwargs: dict[str, Any] = {
                "ping_interval": getattr(self.stream_cfg, "ping_interval_s", 20.0),  # type: ignore[attr-defined]
                "ping_timeout": max(5.0, float(getattr(self.stream_cfg, "ping_interval_s", 20.0)) * 2.0),  # type: ignore[attr-defined]
                "max_size": None,
                "compression": None,
            }

            try:
                # najpierw zgodnie z poprzednim kodem (mocki mogły tego wymagać)
                self.websocket = await wsmod.connect(  # type: ignore[attr-defined]
                    endpoint,
                    additional_headers=headers,  # type: ignore[call-arg]
                    **connect_kwargs,
                )
            except TypeError:
                # fallback do oficjalnego API `websockets`
                self.websocket = await wsmod.connect(  # type: ignore[attr-defined]
                    endpoint,
                    extra_headers=headers,  # type: ignore[call-arg]
                    **connect_kwargs,
                )

            self.connected = True  # type: ignore[attr-defined]
            self.retry_count = 0  # type: ignore[attr-defined]
            self.session_id = str(uuid.uuid4())  # type: ignore[attr-defined]
            try:
                self.logger.event("ws.connected", session_id=self.session_id)  # type: ignore[attr-defined]
            except Exception:
                pass
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
        while (
            self.retry_count < self.stream_cfg.max_retries  # type: ignore[attr-defined]
            and not self.stop_event.is_set()  # type: ignore[attr-defined]
        ):
            delay_ms = min(
                self.stream_cfg.base_ms * (2**self.retry_count),  # type: ignore[attr-defined]
                self.stream_cfg.max_ms,  # type: ignore[attr-defined]
            )
            try:
                self.logger.event(  # type: ignore[attr-defined]
                    "ws.reconnect_attempt",
                    retry=self.retry_count + 1,  # type: ignore[attr-defined]
                    delay_ms=delay_ms,
                )
            except Exception:
                pass

            await asyncio.sleep(delay_ms / 1000.0)

            if await self._connect():
                await self._send_session_update()  # type: ignore[attr-defined]
                return True

            self.retry_count += 1  # type: ignore[attr-defined]

        try:
            self.logger.event(  # type: ignore[attr-defined]
                "ws.reconnect_exhausted",
                max_retries=self.stream_cfg.max_retries,  # type: ignore[attr-defined]
            )
        except Exception:
            pass
        try:
            self._publish_error("ws_connect", "Connection failed after max retries")  # type: ignore[attr-defined]
        except Exception:
            pass
        return False
