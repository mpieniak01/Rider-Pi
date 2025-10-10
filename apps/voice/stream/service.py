# apps/voice/stream/service.py
"""Refactored streaming voice service using transport and state modules.

This is a streamlined version of the original streaming service,
focusing on orchestration while delegating transport and state management.

The service is composed of mixins:
- StreamHandlersMixin: Message/event handlers, callbacks, session init
- StreamPlayoutMixin: Audio capture and TTS playback workers
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any

from .. import voice_logging
from ..capture import CaptureConfig
from ..chat import ChatConfig, ChatSession
from ..common import ensure_event_logger
from ..playback import PlaybackConfig
from ..rt_protocol import build_audio_commit, build_response_create
from ..stream_chunks import AudioChunkProcessor
from ..tts import TTSConfig
from ..utils import run_sync
from .handlers import StreamHandlersMixin
from .playout import StreamPlayoutMixin
from .state import PTTEvent, PTTStateMachine
from .transport import ReconnectingTransport


@dataclass
class StreamConfig:
    """Configuration for WebSocket streaming."""

    protocol: str = "websocket"
    endpoint: str = ""
    auth: str = ""
    chunk_ms: int = 20
    sample_rate: int = 16000
    turn_end_silence_ms: int = 700
    max_turn_ms: int = 6000
    send_partials: bool = True
    server_vad: bool = True
    local_vad_fallback: bool = True
    ping_interval_s: int = 10

    # Reconnect settings
    max_retries: int = 6
    base_ms: int = 250
    max_ms: int = 5000

    # Audio settings
    jitter_buffer_ms: int = 120
    barge_in: bool = True

    @classmethod
    def from_dict(cls, cfg: dict[str, Any]) -> StreamConfig:
        """Create StreamConfig from dictionary, handling nested structures."""
        stream_cfg = cfg.get("stream", {})
        reconnect_cfg = stream_cfg.get("reconnect", {})
        audio_cfg = stream_cfg.get("audio", {})

        return cls(
            protocol=stream_cfg.get("protocol", "websocket"),
            endpoint=stream_cfg.get("endpoint", ""),
            auth=stream_cfg.get("auth", ""),
            chunk_ms=int(stream_cfg.get("chunk_ms", 20)),
            sample_rate=int(stream_cfg.get("sample_rate", 16000)),
            turn_end_silence_ms=int(stream_cfg.get("turn_end_silence_ms", 700)),
            max_turn_ms=int(stream_cfg.get("max_turn_ms", 6000)),
            send_partials=bool(stream_cfg.get("send_partials", True)),
            server_vad=bool(stream_cfg.get("server_vad", True)),
            local_vad_fallback=bool(stream_cfg.get("local_vad_fallback", True)),
            ping_interval_s=int(stream_cfg.get("ping_interval_s", 10)),
            max_retries=int(reconnect_cfg.get("max_retries", 6)),
            base_ms=int(reconnect_cfg.get("base_ms", 250)),
            max_ms=int(reconnect_cfg.get("max_ms", 5000)),
            jitter_buffer_ms=int(audio_cfg.get("jitter_buffer_ms", 120)),
            barge_in=bool(audio_cfg.get("barge_in", True)),
        )


class StreamingVoiceService(StreamHandlersMixin, StreamPlayoutMixin):
    async def connect(self, *args, **kwargs) -> bool:
        """Bezpieczne łączenie: nie propaguje wyjątku, publikuje ui.error i zwraca False."""
        try:
            # Oczekujemy, że _connect_inner podniesie wyjątek przy błędzie
            if hasattr(self, "_connect_inner"):
                return await self._connect_inner(*args, **kwargs)
            # Wsteczna kompatybilność: jeśli istnieje stary _connect, deleguj
            if hasattr(self, "_connect"):
                return await self._connect(*args, **kwargs)  # type: ignore[misc]
            # Jeśli nic nie ma – uznaj jako błąd
            raise RuntimeError("No connect implementation")
        except Exception as e:
            self.connected = False
            # Publikujemy błąd w formacie sprawdzanym przez test
            self._publish_error("ws_connect", e)
            # Opcjonalny log – nie zmieniamy poziomu logowania testów
            logger = logging.getLogger(getattr(self, "log_name", "voice.stream"))
            try:
                logger.warning("connect failed: %s", e)
            except Exception:
                pass
            return False

    def _publish_error(self, err_type: str, message: str) -> None:
        """Publikuj błąd do UI w formacie oczekiwanym przez testy."""
        payload = {
            "type": err_type,
            "message": str(message),
            "ts": datetime.utcnow().isoformat() + "Z",
        }
        pub = getattr(self, "ui_publisher", None)
        if pub and hasattr(pub, "publish"):
            try:
                pub.publish("ui.error", payload)
            except Exception:  # nie chcemy, by publikacja błędu psuła dalszy flow
                pass

    """Refactored WebSocket-based streaming voice service."""

    def __init__(self, config: dict[str, Any], ui_publisher: Any | None = None) -> None:
        self.config = config
        self.stream_cfg = StreamConfig.from_dict(config)
        self.ui_publisher = ui_publisher
        self.logger = ensure_event_logger(voice_logging.get_logger("voice.stream"))

        # Transport layer
        self.transport: ReconnectingTransport | None = None

        # State machine
        self.ptt_state = PTTStateMachine(self.logger)
        self._setup_state_callbacks()

        # Threading / queues
        self.audio_queue: queue.Queue[bytes | None] = queue.Queue()
        self.tts_player_queue: queue.Queue[bytes | None] = queue.Queue()
        self.stop_event = threading.Event()
        self.barge_in_event = threading.Event()

        # Worker tasks/threads
        self._capture_thread: threading.Thread | None = None
        self._tts_player_thread: threading.Thread | None = None
        self._message_handler_task: asyncio.Task[None] | None = None
        self._audio_sender_task: asyncio.Task[None] | None = None
        self._keyboard_task: asyncio.Task[None] | None = None

        # Session state
        self.session_id: str = ""
        self.partial_transcript = ""
        self._completed: bool = False
        self._session_prefs: Any | None = None
        self._commit_lock = asyncio.Lock()
        self._chunk_counter = 0

        # RX watchdog
        self._last_rx_ts: float = time.time()

        # TX timers (dla commitów bez lokalnego VAD)
        self._last_audio_ts: float = 0.0
        self._last_commit_ts: float = time.time()

        # --- Bandwidth metrics (pojedynczy event na koniec sesji) ------------
        self._bw_tx_total: int = 0
        self._bw_rx_total: int = 0
        self._bw_started_ts: float = time.time()
        # ---------------------------------------------------------------------

        # Capture configuration for chunk processing
        capture_in = dict(self.config.get("capture", {}) or {})
        try:
            valid_fields = {field.name for field in fields(CaptureConfig)}
            capture_in = {k: v for k, v in capture_in.items() if k in valid_fields}
            self._capture_cfg = CaptureConfig(**capture_in)
        except Exception:
            self._capture_cfg = CaptureConfig()

        self._capture_cfg_dict = {
            "backend": self._capture_cfg.backend,
            "device": self._capture_cfg.device,
            "sample_rate": self._capture_cfg.sample_rate,
            "channels": self._capture_cfg.channels,
            "frame_ms": self._capture_cfg.frame_ms,
            "buffer_seconds": self._capture_cfg.buffer_seconds,
            "sample_format": self._capture_cfg.sample_format,
        }
        # Zostawiamy dla ewentualnych przyszłych optymalizacji, ale nie używamy bezpośrednio do wysyłki
        self._chunk_processor = AudioChunkProcessor(self._capture_cfg, self.stream_cfg, self.logger)

        # Chat configuration for streaming mode
        chat_in = dict(self.config.get("chat", {}) or {})
        self._chat_cfg = ChatConfig(
            backend=chat_in.get("backend", "openai"),
            model=chat_in.get("model", "gpt-4o-mini"),
            system_prompt=chat_in.get("system_prompt", "Jesteś asystentem robota. Odpowiadaj krótko i po polsku."),
            max_history=int(chat_in.get("max_history", 4)),
            max_tokens=chat_in.get("max_tokens"),
            transport="realtime",
        )
        self._chat_session: ChatSession | None = None

        # TTS configuration for streaming mode
        tts_in = dict(self.config.get("tts", {}) or {})
        self._tts_cfg = TTSConfig(
            backend=tts_in.get("backend", "openai"),
            voice=tts_in.get("voice", "alloy"),
            model=tts_in.get("model", "gpt-4o-mini-tts"),
            format=tts_in.get("format", "mp3"),
            timeout=tts_in.get("timeout"),
            transport="realtime",
        )

        # Playback configuration for TTS
        playback_in = dict(self.config.get("playback", {}) or {})
        self._playback_cfg = PlaybackConfig(
            backend=playback_in.get("backend", "alsa"),
            device=playback_in.get("device"),
        )

        # PTT configuration (compatible with old svc_stream.py logic)
        hotword_cfg = dict(self.config.get("hotword") or {})
        ptt_cfg = self.config.get("ptt") or {}
        service_cfg = self.config.get("service") or {}
        turn_cfg = service_cfg.get("turn") or self.config.get("turn") or {}

        service_hotword_engine = str(service_cfg.get("hotword_engine", "")).strip().lower()
        service_hotword_enabled = service_cfg.get("hotword_enabled")
        commit_on_key = bool(turn_cfg.get("commit_on_key", False))

        hotword_engine = str(hotword_cfg.get("engine", "")).strip().lower()
        if not hotword_engine:
            if service_hotword_engine:
                hotword_engine = service_hotword_engine
            elif service_hotword_enabled is False:
                hotword_engine = ""
            else:
                hotword_engine = "ptt"

        self.ptt_enabled: bool = hotword_engine == "ptt" or bool(ptt_cfg.get("enabled", False)) or commit_on_key
        if service_hotword_enabled is False:
            self.ptt_enabled = False

        self._any_audio_since_commit: bool = False

        # Compatibility shims
        class _PTTControllerShim:
            def __init__(self, parent):
                self._parent = parent

            @property
            def ptt_enabled(self):
                return self._parent.ptt_enabled

        class _AudioTransmitterShim:
            def __init__(self, parent):
                self._parent = parent

            @property
            def ptt_enabled(self):
                return self._parent.ptt_enabled

        self.ptt_controller = _PTTControllerShim(self)
        self.audio_transmitter = _AudioTransmitterShim(self)

        # Additional compatibility attributes
        self.connected = False
        self.websocket: Any | None = None
        self.current_state = "idle"
        self._last_ui_state: str | None = None

        self._loop: asyncio.AbstractEventLoop | None = None

    # ──────────────────────────────────────────────────────────────────────────
    # Transport & session

    async def _initialize_transport(self) -> bool:
        """Initialize WebSocket transport."""
        try:
            auth_header = self._get_auth_header()
            self.transport = ReconnectingTransport(
                endpoint=self.stream_cfg.endpoint,
                auth_header=f"Bearer {auth_header}",
                max_retries=self.stream_cfg.max_retries,
                base_ms=self.stream_cfg.base_ms,
                max_ms=self.stream_cfg.max_ms,
                ping_interval_s=self.stream_cfg.ping_interval_s,
                logger=self.logger,
            )
            self.logger.event(
                "stream.config",
                endpoint=self._mask_endpoint(self.stream_cfg.endpoint),
                chunk_ms=self.stream_cfg.chunk_ms,
                sample_rate=self.stream_cfg.sample_rate,
                silence_ms=self.stream_cfg.turn_end_silence_ms,
                max_turn_ms=self.stream_cfg.max_turn_ms,
                server_vad=int(self.stream_cfg.server_vad),
                send_partials=int(self.stream_cfg.send_partials),
                barge_in=int(self.stream_cfg.barge_in),
            )
            return True
        except Exception as e:
            self.logger.event("transport.init.error", error=str(e))
            return False

    async def _transition_to_idle(self) -> None:
        """Async helper to transition from CLOSING to IDLE."""
        await asyncio.sleep(0.05)
        self.ptt_state.transition(PTTEvent.TIMEOUT)

    # ──────────────────────────────────────────────────────────────────────────
    # UI publish (delegated to StreamHandlersMixin)
    # _publish_ui_state, _publish_partial, _publish_error are in handlers.py

    # ──────────────────────────────────────────────────────────────────────────
    # Public API

    async def once(self, *, speak: bool = True) -> dict[str, Any] | None:
        """Single interaction mode."""
        self._loop = asyncio.get_running_loop()
        self.logger.event("stream.once.start")

        if not await self._initialize_transport():
            return None

        try:
            await self._send_session_init()
            self._message_handler_task = asyncio.create_task(self._message_handler_loop())
            self._audio_sender_task = asyncio.create_task(self._audio_sender_loop())
            self._start_audio_capture()
            if speak:
                self._start_tts_player()
            self.ptt_state.start_interaction()
            self.ptt_state.transition(PTTEvent.START)

            timeout_s = self.stream_cfg.max_turn_ms / 1000.0 + 10
            try:
                await asyncio.wait_for(self._wait_for_completion(), timeout=timeout_s)
            except asyncio.TimeoutError:
                self.logger.event("stream.once.timeout")
                self.ptt_state.transition(PTTEvent.TIMEOUT)

            return {"completed": self._completed, "session_id": self.session_id}
        finally:
            await self._cleanup()

    async def listen(self) -> None:
        """Continuous listening mode."""
        self._loop = asyncio.get_running_loop()
        self.logger.event("stream.listen.start")
        self._publish_ui_state("idle")

        if not await self._initialize_transport():
            return

        try:
            await self._run_with_reconnect()
        except KeyboardInterrupt:
            self.logger.event("stream.listen.interrupted")
        except Exception as e:
            self.logger.event("stream.listen.error", error=str(e))
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop the service (safe from sync code)."""
        self.logger.event("stream.stop")
        self.stop_event.set()
        try:
            self.tts_player_queue.put_nowait(None)
        except Exception:
            pass
        if self._loop:
            try:
                fut = asyncio.run_coroutine_threadsafe(self._cleanup(), self._loop)
                try:
                    _ = fut.result(timeout=3.0)
                except Exception as e:
                    self.logger.event("stream.stop.cleanup_wait_error", error=str(e))
            except Exception as e:
                self.logger.event("stream.stop.cleanup_schedule_error", error=str(e))
        else:
            try:
                run_sync(self._cleanup())
            except Exception as e:
                self.logger.event("stream.stop.cleanup_sync_error", error=str(e))

    async def close(self) -> None:
        """Close the service (compatibility alias for stop, async version)."""
        await self._cleanup()

    # ──────────────────────────────────────────────────────────────────────────
    # Session run loops

    async def _run_with_reconnect(self) -> None:
        """Run session with reconnection handling."""
        while not self.stop_event.is_set():
            try:
                await self._run_session()
                if self.stop_event.is_set():
                    break
                self._cleanup_workers()
                self._publish_ui_state("idle")
            except Exception as e:
                self.logger.event("stream.session_error", error=str(e))
                break

    async def _run_session(self) -> None:
        """Run a single WebSocket session."""
        await self._send_session_init()
        self._start_audio_capture()
        self._start_tts_player()
        self._audio_sender_task = asyncio.create_task(self._audio_sender_loop())
        self._message_handler_task = asyncio.create_task(self._message_handler_loop())

        # Start PTT keyboard handler if enabled
        if self.ptt_enabled:
            self._keyboard_task = asyncio.create_task(self._keyboard_ptt_loop())

        # prosty watchdog RX – jeśli nie ma eventów, ostrzegaj
        async def _rx_watchdog():
            while not self.stop_event.is_set():
                await asyncio.sleep(5)
                delta = time.time() - self._last_rx_ts
                if delta > 5:
                    self.logger.event("ws.no_rx", since_s=int(delta))

        asyncio.create_task(_rx_watchdog())

        # Keep the session alive while other tasks are running.
        while not self.stop_event.is_set() and self.transport:
            await asyncio.sleep(0.1)

    # ──────────────────────────────────────────────────────────────────────────
    # Messaging (delegated to StreamHandlersMixin)
    # _normalize_type, _message_handler_loop, _handle_message, _handle_transcript are in handlers.py

    # ──────────────────────────────────────────────────────────────────────────
    # Keyboard PTT (delegated to StreamHandlersMixin)
    # _keyboard_ptt_loop, _play_ding_async are in handlers.py

    # ──────────────────────────────────────────────────────────────────────────
    # Workers

    async def _audio_sender_loop(self) -> None:
        """Send captured audio frames to the realtime API."""
        self.logger.event("audio.sender.start")
        silence_s = max(0.2, self.stream_cfg.turn_end_silence_ms / 1000.0)
        hard_cap_s = max(1.0, self.stream_cfg.max_turn_ms / 1000.0)
        try:
            while not self.stop_event.is_set():
                now = time.time()

                if self._any_audio_since_commit:
                    if (now - self._last_audio_ts) >= silence_s:
                        try:
                            self.logger.event(
                                "audio.commit.timer_silence",
                                idle_ms=int((now - self._last_audio_ts) * 1000),
                            )
                            await self._commit_audio_buffer()
                            self._last_commit_ts = time.time()
                        except Exception:
                            pass
                    elif (now - self._last_commit_ts) >= hard_cap_s:
                        try:
                            self.logger.event(
                                "audio.commit.timer_maxturn",
                                elapsed_ms=int((now - self._last_commit_ts) * 1000),
                            )
                            await self._commit_audio_buffer()
                            self._last_commit_ts = time.time()
                        except Exception:
                            pass

                try:
                    chunk = self.audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                if chunk is None:
                    if self._any_audio_since_commit:
                        await self._commit_audio_buffer()
                    if self.stop_event.is_set():
                        break
                    continue

                await self._send_audio_chunk(chunk)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.event("audio.sender.error", error=str(e))
        finally:
            self.logger.event("audio.sender.stop")

    async def _send_audio_chunk(self, chunk: bytes) -> None:
        """Wyślij kawałek audio; gdy wejście jest stereo, downmix do mono i zaloguj metryki."""

        def _downmix_to_mono_local(b: bytes) -> bytes:
            # 16-bit PCM stereo interleaved: L(2B) R(2B) -> bierzemy L (szybko)
            out = bytearray()
            for i in range(0, len(b), 4):
                out += b[i : i + 2]
            return bytes(out)

        def _encode_audio_append_local(b: bytes) -> str:
            import base64 as _b64
            import json as _json

            return _json.dumps(
                {
                    "type": "input_audio_buffer.append",
                    "audio": _b64.b64encode(b).decode("ascii"),
                }
            )

        channels_cfg = getattr(getattr(self, "capture_cfg", None), "channels", None)
        if channels_cfg is None:
            try:
                channels_cfg = int(self.config.get("capture", {}).get("channels", 1))  # type: ignore[attr-defined]
            except Exception:
                channels_cfg = 1

        guessed_is_stereo = len(chunk) >= 4 and len(chunk) % 4 == 0
        ch_in = 2 if (channels_cfg == 2 or (channels_cfg != 1 and guessed_is_stereo)) else 1

        if ch_in == 2:
            pcm_out = _downmix_to_mono_local(chunk)
            ch_out = 1
        else:
            pcm_out = chunk
            ch_out = 1

        out_bytes_len = len(pcm_out)
        msg = _encode_audio_append_local(pcm_out)

        sender = None
        if getattr(self, "transport", None) and hasattr(self.transport, "send"):
            sender = self.transport.send
        elif getattr(self, "websocket", None) and hasattr(self.websocket, "send"):
            sender = self.websocket.send

        if sender:
            res = sender(msg)
            import inspect as _inspect

            if _inspect.isawaitable(res):
                await res

        try:
            self._bw_tx_total += out_bytes_len
        except Exception:
            pass

        self._any_audio_since_commit = True
        self._last_audio_ts = time.time()

        self.logger.event(
            "stream.tx",
            ch_in=ch_in,
            ch_out=ch_out,
            sr=16000,
            bytes_in=len(chunk),
            bytes_out=out_bytes_len,
        )

    async def _commit_audio_buffer(self) -> None:
        """Close the current input buffer and request a response."""
        async with self._commit_lock:
            if not self.transport:
                self.logger.event("audio.commit.skip", reason="no_transport")
                return
            if not self._any_audio_since_commit:
                self.logger.event("audio.commit.skip", reason="empty")
                return

            try:
                await self.transport.send(build_audio_commit())
                self.logger.event("audio.commit")
            except Exception as e:
                self.logger.event("audio.commit.error", error=str(e))
                raise
            finally:
                self._any_audio_since_commit = False

            await self._send_response_create()

    async def _send_response_create(self) -> None:
        """Request assistant response generation."""
        if not self.transport:
            return

        prefs = self._session_prefs
        modalities = getattr(prefs, "modalities", None) or ["text", "audio"]
        voice = getattr(prefs, "voice", None) or getattr(self._tts_cfg, "voice", "alloy") or "alloy"
        instructions = (
            getattr(prefs, "instructions", "") or "Jesteś asystentem głosowym Rider-Pi. Odpowiadaj po polsku."
        )

        try:
            message = build_response_create(voice=voice, instructions=instructions, modalities=list(modalities))
            await self.transport.send(message)
            self.logger.event("response.create", voice=voice, modalities=",".join(modalities))
        except Exception as e:
            self.logger.event("response.create.error", error=str(e))
            raise

    # ──────────────────────────────────────────────────────────────────────────
    # Workers (delegated to StreamPlayoutMixin)
    # _start_audio_capture, _start_tts_player, _cleanup_workers are in playout.py

    # ──────────────────────────────────────────────────────────────────────────
    # Cleanup

    async def _cleanup(self) -> None:
        """Full cleanup including transport."""
        if self._audio_sender_task and not self._audio_sender_task.done():
            self._audio_sender_task.cancel()
            try:
                await self._audio_sender_task
            except asyncio.CancelledError:
                pass
            finally:
                self._audio_sender_task = None

        if self._message_handler_task and not self._message_handler_task.done():
            self._message_handler_task.cancel()
            try:
                await self._message_handler_task
            except asyncio.CancelledError:
                pass
            finally:
                self._message_handler_task = None

        if self._keyboard_task and not self._keyboard_task.done():
            self._keyboard_task.cancel()
            try:
                await self._keyboard_task
            except asyncio.CancelledError:
                pass
            finally:
                self._keyboard_task = None

        if self.transport:
            try:
                await self.transport.close()
            except Exception as e:
                self.logger.event("transport.close.error", error=str(e))
            finally:
                self.transport = None

        if self.websocket:
            try:
                await self.websocket.close(code=1000)
                await self.websocket.wait_closed()
            except Exception as e:
                self.logger.event("websocket.close.error", error=str(e))
            finally:
                self.websocket = None
                self.connected = False

        # Emit one final bandwidth metric (spełnia wymagania testu)
        try:
            window_s = max(0.001, time.time() - self._bw_started_ts)
            data = {
                "tx_bytes": int(self._bw_tx_total),
                "rx_bytes": int(self._bw_rx_total),
                "window_s": float(window_s),
                "tx_bps": float(self._bw_tx_total) / window_s,
                "rx_bps": float(self._bw_rx_total) / window_s if self._bw_rx_total else 0.0,
                "phase": "final",
            }
            self.logger.event("stream.bw", **data)
        except Exception:
            # metryka pomocnicza – ignorujemy błędy przy zamykaniu
            pass

        self._cleanup_workers()
        self.ptt_state.reset()
        self._publish_ui_state("idle")

    # ──────────────────────────────────────────────────────────────────────────
    # Waiters

    async def _wait_for_completion(self) -> None:
        """Wait for interaction completion."""
        while not self._completed and not self.stop_event.is_set():
            await asyncio.sleep(0.1)

    def _mask_endpoint(self, endpoint: str) -> str:
        if not endpoint:
            return ""
        return endpoint.replace("model=", "model=***")

    # ──────────────────────────────────────────────────────────────────────────
    # Test compatibility aliases (delegated to StreamHandlersMixin)
    # _send_session_update, _handle_ws_message are in handlers.py
