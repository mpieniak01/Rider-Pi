# apps/voice/svc_stream.py
"""WebSocket streaming voice service - duplex realtime ASR→CHAT→TTS pipeline."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

# 3rd-party (wstrzykiwane do transportu przez self._ws_module)
try:
    import websockets  # type: ignore
except Exception:  # pragma: no cover

    class _WSStub:
        def __getattr__(self, _):  # minimalny stub dla testów
            raise RuntimeError("websockets unavailable")

    websockets = _WSStub()  # type: ignore

# Lokalne moduły
from . import voice_logging
from .audio_rx_tts import AudioReceiver
from .audio_tx import AudioTransmitter
from .capture import CaptureConfig
from .common import ensure_event_logger
from .playback import play_ding  # noqa: F401 - Re-export for test compatibility
from .ptt_state import PTTController
from .rt_protocol import build_response_cancel
from .state import StreamingVoicePTTMixin
from .stream_chunks import (
    AudioChunkProcessor,
    decode_audio_from_message,
)
from .transport import StreamingVoiceTransportMixin
from .voice_metrics import VoiceMetrics


# ────────────────────────────────────────────────────────────────────────────
# Anti-spam / ENV utils
# ────────────────────────────────────────────────────────────────────────────
def _env_int(name: str, default: int) -> int:
    try:
        raw = os.environ.get(name, "")
        return int(raw.strip() or default)
    except Exception:
        return default


def _env_flag(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip() in ("1", "true", "True", "yes", "YES")


class _TxLogger:
    """Agreguje telemetrię dla stream.tx i ogranicza spam logów."""

    def __init__(self, logger) -> None:
        self.logger = logger
        self._sec = int(time.time())
        self._n = 0
        self._bytes_in = 0
        self._bytes_out = 0
        # przy 20 ms ~= 50 chunków/sek
        self._sample_every = max(1, _env_int("VOICE_TX_SAMPLE_EVERY", 50))

    def on_chunk(self, telemetry: dict) -> None:
        self._n += 1
        self._bytes_in += int(telemetry.get("bytes_in", 0))
        self._bytes_out += int(telemetry.get("bytes_out", 0))
        now = int(time.time())

        # loguj co N-ty chunk lub przy zmianie sekundy
        if (self._n % self._sample_every) != 0 and now == self._sec:
            return

        self.logger.event(
            "stream.tx",
            bytes_in=self._bytes_in,
            bytes_out=self._bytes_out,
            chunks=self._n,
            ch_in=telemetry.get("ch_in", 1),
            ch_out=telemetry.get("ch_out", 1),
            sr=telemetry.get("sr", 16000),
            chunk_ms=telemetry.get("chunk_ms", 20),
        )

        # reset raz na sekundę albo po logu co N
        if now != self._sec:
            self._sec = now
            self._n = 0
            self._bytes_in = 0
            self._bytes_out = 0


RECV_DUMP_PATH = "/tmp/voice-ws-recv.jsonl"


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

    # Request trigger
    request_on_commit: bool = True

    @classmethod
    def from_dict(cls, cfg: dict[str, Any]) -> StreamConfig:
        """Create StreamConfig from dictionary, handling nested structures."""
        stream_cfg = cfg.get("stream", {}) or {}
        reconnect_cfg = stream_cfg.get("reconnect", {}) or {}
        audio_cfg = stream_cfg.get("audio", {}) or {}

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
            request_on_commit=bool(stream_cfg.get("request_on_commit", True)),
        )


class StreamingVoiceService(StreamingVoiceTransportMixin, StreamingVoicePTTMixin):
    """WebSocket-based streaming voice service with duplex audio."""

    def __init__(self, config: dict[str, Any], ui_publisher: Any | None = None) -> None:
        self._session_update_sent = False
        self.config = config
        self.stream_cfg = StreamConfig.from_dict(config)
        self.ui_publisher = ui_publisher
        self.logger = ensure_event_logger(voice_logging.get_logger("voice.stream"))

        # Runtime state
        self.websocket: Any = None
        self.session_id: str = ""
        self.current_state = "idle"
        # Bounded queues for backpressure (prevent unbounded growth)
        audio_queue_maxsize = _env_int("VOICE_AUDIO_QUEUE_MAX", 200)  # ~4s @ 20ms chunks
        tts_queue_maxsize = _env_int("VOICE_TTS_QUEUE_MAX", 500)  # ~10s @ 20ms chunks
        self.audio_queue: queue.Queue[bytes | None] = queue.Queue(maxsize=audio_queue_maxsize)
        self.tts_player_queue: queue.Queue[bytes | None] = queue.Queue(maxsize=tts_queue_maxsize)
        self.stop_event = threading.Event()
        self.barge_in_event = threading.Event()

        # Counters for dropped chunks (backpressure metrics)
        self._audio_drops = 0
        self._tts_drops = 0

        # workers (dla join/stop)
        self._capture_thread: threading.Thread | None = None
        self._tts_thread: threading.Thread | None = None
        self._ptt_thread: threading.Thread | None = None

        # async taski
        self._sender_task: asyncio.Task | None = None
        self._recv_task: asyncio.Task | None = None
        self._guard_task: asyncio.Task | None = None
        self._nudge_task: asyncio.Task | None = None

        # Partial transcript tracking
        self.partial_transcript = ""

        # Connection state
        self.connected = False
        self.retry_count = 0
        self._connection_start_ts: float = 0.0  # Track connection lifetime

        # one-shot interaction flag
        self._completed: bool = False

        # --- PTT (push-to-talk) sterowanie Enterem ---
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
                # Kompatybilność: domyślnie traktuj brak konfiguracji jako PTT
                hotword_engine = "ptt"

        self.ptt_enabled: bool = (
            hotword_engine == "ptt"
            or bool(ptt_cfg.get("enabled", False))
            or commit_on_key
        )
        if service_hotword_enabled is False:
            self.ptt_enabled = False

        # zachowaj wyliczony engine (dla debugowania/ew. przyszłego użycia)
        self._ptt_engine = hotword_engine
        self.ptt_active: bool = False  # czy aktualnie nagrywamy po Enter
        self._ptt_was_active: bool = False  # detekcja zbocza STOP (True->False)
        self._any_audio_since_commit: bool = False  # czy coś poleciało od startu PTT
        self._loop: asyncio.AbstractEventLoop | None = None  # główna pętla do commitów z wątku

        # strażnik odpowiedzi po commit
        self._response_pending: bool = False
        self._last_commit_ts: float = 0.0
        self._last_commit_future: Any = None  # Future z run_coroutine_threadsafe (dla PTT watchdog)

        # cache CaptureConfig dla ensure_mono_16k (zamiast tworzyć per chunk)
        try:
            self._capture_cfg_obj = CaptureConfig(**(self.config.get("capture", {}) or {}))
        except Exception:
            # fallback – minimalny config (16k/mono)
            self._capture_cfg_obj = CaptureConfig(
                backend="alsa",
                device=(self.config.get("capture", {}) or {}).get("device", "plughw:wm8960soundcard,0"),
                sample_rate=int((self.config.get("capture", {}) or {}).get("sample_rate", 16000)),
                channels=int((self.config.get("capture", {}) or {}).get("channels", 1)),
                frame_ms=int((self.config.get("capture", {}) or {}).get("frame_ms", 20)),
                buffer_seconds=float((self.config.get("capture", {}) or {}).get("buffer_seconds", 0.1)),
                sample_format=str((self.config.get("capture", {}) or {}).get("sample_format", "S16_LE")).upper(),
            )

        # Umożliwia testom patchować websockets na poziomie modułu svc_stream
        self._ws_module = websockets

        # Anti-spam agregator do logów stream.tx
        self._txlog = _TxLogger(self.logger)

        # --- Response guard i commit PTT sterowane ENV ---
        self._resp_guard_ms: int = _env_int("VOICE_RESPONSE_GUARD_MS", 400)
        self._ptt_commit_sync: bool = _env_flag("VOICE_PTT_COMMIT_SYNC", False)
        self._ptt_commit_timeout_ms: int = _env_int("VOICE_PTT_COMMIT_TIMEOUT_MS", 1500)

        # --- New modular components (PR-2) ---
        self.metrics = VoiceMetrics()

        # Audio transmitter (capture → queue)
        self.audio_transmitter = AudioTransmitter(
            config=self.config,
            stream_cfg=self.stream_cfg,
            audio_queue=self.audio_queue,
            logger=self.logger,
            stop_event=self.stop_event,
            ptt_enabled=self.ptt_enabled,
        )
        # Wire callbacks
        self.audio_transmitter.on_ptt_commit = self._schedule_commit
        self.audio_transmitter.on_barge_in = self._handle_barge_in_from_capture

        # Audio receiver (queue → playback)
        self.audio_receiver = AudioReceiver(
            config=self.config,
            stream_cfg=self.stream_cfg,
            tts_queue=self.tts_player_queue,
            logger=self.logger,
            stop_event=self.stop_event,
            barge_in_event=self.barge_in_event,
        )
        # Wire callbacks
        self.audio_receiver.on_playback_start = lambda: self._publish_ui_state("speaking")
        self.audio_receiver.on_playback_end = lambda: self._publish_ui_state("idle")

        # PTT controller (keyboard → commit)
        self.ptt_controller = PTTController(
            logger=self.logger,
            config=self.config,
            stop_event=self.stop_event,
        )
        self.ptt_controller.ptt_enabled = self.ptt_enabled
        # Wire callbacks
        self.ptt_controller.on_commit = self._schedule_commit
        self.ptt_controller.on_state_change = self._publish_ui_state
        self.ptt_controller.on_barge_in = lambda: self.barge_in_event.set()
        self.ptt_controller.on_capture_restart = self._ensure_capture_alive

    # ---- Transport methods are provided by StreamingVoiceTransportMixin ----
    # send(), recv(), aclose(), close(), close_sync(), _connect(), _reconnect_loop()

    def __del__(self) -> None:
        """Cleanup on deletion - best effort, no guarantees in __del__."""
        # Skip cleanup in __del__ entirely to avoid unawaited coroutine warnings.
        # Proper cleanup should happen via explicit close() or stop() calls.
        # __del__ is not a reliable place for async cleanup in Python.
        pass

    def stop(self) -> None:
        """Stop the streaming service (idempotent, test-friendly)."""
        # 0) Flagi stopu
        try:
            self.stop_event.set()
        except Exception:
            pass
        try:
            self._stopping = True
            if hasattr(self, "_running"):
                self._running = False
            if hasattr(self, "ptt_active"):
                self.ptt_active = False
            log = getattr(self.logger, "event", None)
            if callable(log):
                log("stream.stop")
        except Exception:
            pass

        # 0.5) Anuluj asynchroniczne taski, jeśli wiszą
        try:
            for attr in ("_nudge_task", "_guard_task", "_recv_task", "_sender_task"):
                t: asyncio.Task | None = getattr(self, attr, None)
                if t and not t.done():
                    t.cancel()
                    setattr(self, attr, None)
        except Exception as e:
            self.logger.event("stream.stop.task_cancel_failed", error=str(e))

        # 1) Jeśli mamy pętlę, spróbuj zaplanować domknięcie asynchronicznie i wyjść.
        try:
            loop = getattr(self, "_loop", None)
            is_running = getattr(loop, "is_running", lambda: False)()
            if is_running:
                try:
                    if hasattr(self, "aclose"):
                        asyncio.run_coroutine_threadsafe(self.aclose(), loop)
                        return
                    if hasattr(self, "close") and asyncio.iscoroutinefunction(self.close):  # type: ignore[attr-defined]
                        fut = asyncio.run_coroutine_threadsafe(self.close(), loop)  # type: ignore[misc]
                        _ = fut  # silence linters
                        return
                except Exception as e:
                    self.logger.event("stream.stop.schedule_failed", error=str(e))
        except Exception as e:
            self.logger.event("stream.stop.loop_probe_failed", error=str(e))

        # 2) Preferuj API synchroniczne, jeśli jest dostępne.
        try:
            if hasattr(self, "close_sync"):
                self.close_sync()
                self.logger.event("stream.stop.ok", via="close_sync")
                return
        except Exception as e:
            self.logger.event("stream.stop.close_sync_failed", error=str(e))

        # 3) Fallback: zablokowane domknięcie aclose()/close() bez warningów.
        try:
            from .utils import run_sync as _run_sync  # lokalny import, łatwy do mockowania
        except Exception:
            _run_sync = None  # type: ignore[assignment]

        try:
            if hasattr(self, "aclose"):
                if _run_sync is not None:
                    _run_sync(self.aclose(), timeout=2.0)
                else:
                    asyncio.run(self.aclose())
                self.logger.event("stream.stop.ok", via="aclose")
                return
        except Exception as e:
            self.logger.event("stream.stop.aclose_failed", error=str(e))

        try:
            if hasattr(self, "close"):
                is_coro_fn = (
                    _run_sync is not None
                    and hasattr(asyncio, "iscoroutinefunction")
                    and asyncio.iscoroutinefunction(self.close)  # type: ignore[arg-type]
                )
                if is_coro_fn:
                    _run_sync(self.close(), timeout=2.0)  # type: ignore[misc]
                else:
                    close_fn = getattr(self, "close", None)
                    if callable(close_fn):
                        close_fn()  # type: ignore[call-arg]
                self.logger.event("stream.stop.ok", via="close")
                return
        except Exception as e:
            self.logger.event("stream.stop.close_failed", error=str(e))
            # Ostatecznie: nic więcej nie robimy – stop ma być idempotentny.

    def _get_auth_header(self) -> str:
        """Pobierz klucz API wg schematu:
        - env:VAR            → z ENV
        - file:/path         → z pliku (cała zawartość / 1 linia)
        - raw string         → literal w configu

        SECURITY NOTE: bashenv: scheme has been removed. Use env: or file: instead.
        For shell profile integration, export variables in ~/.bash_profile and source it
        before running the application, or use file: pointing to a dedicated secrets file.
        """

        def _expand(p: str) -> str:
            return os.path.expanduser(os.path.expandvars(p))

        def _from_file(path: str) -> str:
            path = _expand(path)
            try:
                with open(path, encoding="utf-8", errors="ignore") as f:
                    return f.read().strip()
            except FileNotFoundError:
                self.logger.event("auth_file_missing", path=path)
                return ""

        auth = (self.stream_cfg.auth or "").strip()

        if auth.startswith("env:"):
            env_key = auth[4:]
            api_key = (os.environ.get(env_key, "") or "").strip()
            if not api_key:
                self.logger.event("auth_missing_key", env_var=env_key)
                raise RuntimeError(f"Missing environment variable: {env_key}.")
            self.logger.event("auth.loaded", src="env", var=env_key, length=len(api_key))
            return api_key

        if auth.startswith("file:"):
            key = _from_file(auth[5:])
            if not key:
                raise RuntimeError(f"API key file empty or not found: {auth[5:]}")
            self.logger.event("auth.loaded", src="file", length=len(key))
            return key

        if auth.startswith("bashenv:"):
            # SECURITY: bashenv scheme is no longer supported
            self.logger.event("auth_bashenv_rejected", auth=auth)
            raise RuntimeError(
                "bashenv: scheme is no longer supported for security reasons. "
                "Use env:VARNAME (with variable exported in shell) or file:/path/to/keyfile instead."
            )

        # fallback: literal w configu
        return auth

    def _publish_ui_state(self, state: str) -> None:
        """Publish UI state change."""
        if state != self.current_state:
            self.current_state = state
            if self.ui_publisher:
                try:
                    self.ui_publisher.publish("ui.state", {"state": state, "ts": time.time()})
                except Exception as e:
                    self.logger.event("ui_state_pub_error", error=str(e))

    def _publish_partial(self, text: str) -> None:
        """Publish partial transcript."""
        if self.ui_publisher and text != self.partial_transcript:
            self.partial_transcript = text
            try:
                self.ui_publisher.publish("ui.partial", {"text": text, "ts": time.time()})
            except Exception as e:
                self.logger.event("partial_pub_error", error=str(e))

    def _publish_error(self, error_type: str, message: str) -> None:
        """Publish error event."""
        if self.ui_publisher:
            try:
                self.ui_publisher.publish("ui.error", {"type": error_type, "message": message, "ts": time.time()})
            except Exception as e:
                self.logger.event("error_pub_error", error=str(e))

    # ----- capture autostart helpers (dla once / hotword=off) -----------------
    def _start_capture(self) -> None:
        """Start capture thread if not already running (used by once/hotword=off)."""
        if self._capture_thread and self._capture_thread.is_alive():
            return

        def _target():
            try:
                self._audio_capture_thread()
            except Exception as e:
                self.logger.event("capture.thread.error", error=str(e))

        self._capture_thread = threading.Thread(
            target=_target,
            name="voice-stream-capture-autostart",
            daemon=True,
        )
        self._capture_thread.start()

    def _stop_capture(self) -> None:
        """Best-effort stop for capture thread started via _start_capture."""
        self.stop_event.set()
        try:
            if self._capture_thread and self._capture_thread.is_alive():
                self._capture_thread.join(timeout=0.5)
        except Exception:
            pass
        finally:
            try:
                self.stop_event.clear()
            except Exception:
                pass
            self._capture_thread = None

    def _handle_barge_in_from_capture(self) -> None:
        """Handle barge-in from audio capture thread."""
        # Send response.cancel to interrupt ongoing response
        if self.connected and self.websocket and self.stream_cfg.barge_in:
            try:
                loop = self._loop
                if loop and hasattr(loop, "is_running") and loop.is_running():
                    asyncio.run_coroutine_threadsafe(self._send_response_cancel(), loop)
            except Exception as e:
                self.logger.event("barge_in.cancel_error", error=str(e))

        # Clear TTS queue on barge-in
        while not self.tts_player_queue.empty():
            try:
                self.tts_player_queue.get_nowait()
            except queue.Empty:
                break

    def _ensure_capture_alive(self) -> None:
        """Ensure capture thread is alive (used by PTT)."""
        try:
            th = getattr(self, "_capture_thread", None)
            if not (th and th.is_alive()):
                self.audio_transmitter.start_capture()
                self._capture_thread = self.audio_transmitter._capture_thread
                self.logger.event("capture.restart.ptt")
        except Exception as e:
            self.logger.event("capture.restart.error", error=str(e))

    # -------------------------------------------------------------------------
    # _connect() is provided by StreamingVoiceTransportMixin (transport.py)
    # -------------------------------------------------------------------------

    async def _send_session_update(self) -> None:
        """Wyślij session.update z pełnymi ustawieniami formatu, modalities, turn_detection."""
        # Idempotentne: wysyłamy tylko raz
        if getattr(self, '_session_update_sent', False):
            return

        # Użyj AudioChunkProcessor do budowy pełnego session.update
        chunk_processor = AudioChunkProcessor(self._capture_cfg_obj, self.stream_cfg, self.logger)
        payload_json = chunk_processor.create_session_update_message(self.config)

        await self.send(payload_json)
        self._session_update_sent = True
        self.logger.event("session.update.sent")

    async def _send_audio_chunk(self, audio_data: bytes) -> None:
        """Send audio chunk to WebSocket i **zawsze** emituj metrykę stream.tx (1×)."""
        if not self.websocket or not audio_data:
            return

        t0 = time.perf_counter()

        # 1) Przetwórz i zakoduj chunk
        chunk_processor = AudioChunkProcessor(self._capture_cfg_obj, self.stream_cfg, self.logger)
        result = chunk_processor.process_and_encode_chunk(audio_data)

        # Wspólne parametry metryki
        ch_in = int(getattr(self._capture_cfg_obj, "channels", 1) or 1)
        sr = int(getattr(self.stream_cfg, "sample_rate", 16000))
        chunk_ms = int(getattr(self.stream_cfg, "chunk_ms", 20))

        if result:
            message_json, telemetry = result
            # 2) Wyślij do WS
            await self.send(message_json)
            self._any_audio_since_commit = True

            # Log audio appended event
            bytes_out = int(telemetry.get("bytes_out", 0))
            self.logger.event("audio.appended", bytes=bytes_out)

            # Record metrics
            bytes_in = int(telemetry.get("bytes_in", len(audio_data)))
            bytes_out = int(telemetry.get("bytes_out", 0))
            self.metrics.on_audio_chunk(bytes_in, bytes_out)

            # 3) Per-chunk metryka
            try:
                duration_ms = max(0, int((time.perf_counter() - t0) * 1000))

                self.logger.event(
                    "stream.tx",
                    sr=sr,
                    ch_in=ch_in,
                    ch_out=1,  # po normalizacji mono
                    bytes_in=bytes_in,
                    bytes_out=bytes_out,
                    chunk_ms=chunk_ms,
                    duration_ms=duration_ms,
                )
            except Exception:
                self.logger.debug("failed to emit per-chunk stream.tx", exc_info=True)

            # 4) Anti-spam agregacja
            self._txlog.on_chunk(
                {
                    "sr": sr,
                    "ch_in": ch_in,
                    "ch_out": 1,
                    "bytes_in": len(audio_data),
                    "bytes_out": int(telemetry.get("bytes_out", 0)),
                    "chunk_ms": chunk_ms,
                }
            )
        else:
            # Fallback: nic nie poszło do WS (np. za mały chunk)
            duration_ms = max(0, int((time.perf_counter() - t0) * 1000))
            self.logger.event(
                "stream.tx",
                sr=sr,
                ch_in=ch_in,
                ch_out=1,
                bytes_in=len(audio_data),
                bytes_out=0,
                chunk_ms=chunk_ms,
                duration_ms=duration_ms,
            )
            self._txlog.on_chunk(
                {
                    "sr": sr,
                    "ch_in": ch_in,
                    "ch_out": 1,
                    "bytes_in": len(audio_data),
                    "bytes_out": 0,
                    "chunk_ms": chunk_ms,
                }
            )

    # ────────────────────────────────────────────────────────────────────────
    # RESPONSE GUARD: dopnij response.create po commit, jeśli serwer milczy
    # ────────────────────────────────────────────────────────────────────────
    async def _send_response_cancel(self) -> None:
        """Send response.cancel to interrupt ongoing response (barge-in)."""
        if not (self.connected and self.websocket):
            return
        try:
            await self.send(build_response_cancel())
            self.logger.event("response.cancel.sent")
            self._response_pending = False
        except Exception as e:
            self.logger.event("response.cancel.error", error=str(e))

    async def _ensure_response_requested(self, force: bool = False) -> None:
        """Wyślij response.create, jeśli jeszcze „wisi” pending po commit."""
        if not (self.connected and self.websocket):
            return
        if not (force or self._response_pending):
            return
        try:
            await self.send(
                json.dumps(
                    {
                        "type": "response.create",
                        "response": {
                            "conversation": "default",
                            "modalities": ["audio", "text"],
                        },
                    }
                )
            )
            self.logger.event("response.create.sent", forced=bool(force))
        except Exception as e:
            self.logger.event("response.create.error", error=str(e))

    async def _delayed_response_guard(self, delay_s: float = 0.4) -> None:
        """Po krótkim czasie od commit sprawdź, czy trzeba dopchnąć response.create."""
        try:
            await asyncio.sleep(max(0.05, delay_s))
            if self._response_pending and (time.time() - self._last_commit_ts) >= delay_s:
                await self._ensure_response_requested(force=not self.stream_cfg.request_on_commit)
        except asyncio.CancelledError:
            return
        except Exception as e:
            self.logger.event("response.guard.error", error=str(e))

    async def _delayed_force_nudge(self, delay_s: float) -> None:
        """Po PTT STOP: delikatny nudge — spróbuj wymusić create TYLKO jeśli commit ustawił pending."""
        try:
            await asyncio.sleep(delay_s)
            if self._response_pending:
                await self._ensure_response_requested(force=True)
                self.logger.event("response.nudge.force")
        except asyncio.CancelledError:
            return
        except Exception as e:
            self.logger.event("response.nudge.error", error=str(e))

    # ────────────────────────────────────────────────────────────────────────
    # PUBLIC (kompat) API dla PTT mixin: schedule commit i zwróć Future
    # ────────────────────────────────────────────────────────────────────────
    def _schedule_commit(self) -> Any:
        """Planowo uruchom _commit_audio_buffer() na pętli i zwróć Future."""
        loop = self._loop
        if loop is None or not getattr(loop, "is_running", lambda: False)():
            self.logger.event("commit.schedule.skip", reason="no_loop")
            return None
        try:
            fut = asyncio.run_coroutine_threadsafe(self._commit_audio_buffer(), loop)
            self._last_commit_future = fut
            self.logger.event("commit.scheduled")

            # Telemetria zakończenia commita (sukces/wyjątek)
            def _done(f: asyncio.Future):
                try:
                    exc = f.exception()
                except Exception as e:
                    self.logger.event("commit.future.done", ok=False, error=str(e))
                    return
                if exc is None:
                    self.logger.event("commit.future.done", ok=True)
                else:
                    self.logger.event("commit.future.done", ok=False, error=str(exc))

            try:
                fut.add_done_callback(_done)  # nie blokuje
            except Exception as _e:
                self.logger.event("commit.future.cb_error", error=str(_e))

            # pre-emptive nudge po opóźnieniu (dla PTT)
            try:
                if self._nudge_task and not self._nudge_task.done():
                    self._nudge_task.cancel()
                self._nudge_task = loop.create_task(
                    self._delayed_force_nudge(max(0.1, self._resp_guard_ms / 1000.0 + 0.2))
                )
            except Exception as _e:
                self.logger.event("response.nudge.schedule_error", error=str(_e))

            # Opcjonalnie: czekaj synchronizująco po STOP (diagnostycznie)
            if self._ptt_commit_sync:
                try:
                    self.logger.event("commit.sync.wait", timeout_ms=self._ptt_commit_timeout_ms)
                    fut.result(timeout=max(0.05, self._ptt_commit_timeout_ms / 1000.0))
                    self.logger.event("commit.sync.ok")
                except Exception as e:
                    self.logger.event("commit.sync.error", error=str(e))

            return fut
        except Exception as e:
            self.logger.event("commit.schedule.error", error=str(e))
            return None

    # aliasy oczekiwane przez niektóre wersje mixinów
    def commit_audio_buffer(self) -> Any:
        """Publiczny wrapper — wywołaj commit i zwróć Future (dla watchdogów PTT)."""
        return self._schedule_commit()

    def commit(self) -> Any:  # czasem mixin zawoła krótszą nazwę
        return self._schedule_commit()

    async def commit_audio_buffer_async(self) -> None:
        """Asynchroniczny wrapper — bezpośrednio await na commit."""
        await self._commit_audio_buffer()

    async def _commit_audio_buffer(self) -> None:
        """Commit the audio buffer and trigger response generation."""
        # marker wejścia
        try:
            self.logger.event("commit.entry")
        except Exception:
            pass

        if not (self.connected and self.websocket):
            try:
                self.logger.event("commit.skip.not_connected")
                self.logger.event("commit.exit", status="skip")
            finally:
                # ruff B012: nie zwracamy z finally
                pass

            return
        # 1) Domknięcie bufora wejściowego audio
        try:
            await self.send(json.dumps({"type": "input_audio_buffer.commit"}))
            self._response_pending = True
            self._last_commit_ts = time.time()
            self.logger.event("audio.committed")

            # Record metrics
            self.metrics.on_commit()
        except Exception as e:
            self.logger.event("commit.send_error", error=str(e))
            try:
                self.logger.event("commit.exit", status="error")
            finally:
                raise

        # 2) Opcjonalnie: natychmiast prośba o odpowiedź
        try:
            if self.stream_cfg.request_on_commit:
                await self._ensure_response_requested(force=False)
            else:
                self.logger.event("response.create.skip")
        except Exception as e:
            self.logger.event("response.create.error", error=str(e))
        finally:
            # 3) Strażnik „dopchnięcia” create
            try:
                if self._guard_task and not self._guard_task.done():
                    self._guard_task.cancel()
                loop = self._loop or asyncio.get_running_loop()
                self._guard_task = loop.create_task(
                    self._delayed_response_guard(max(0.05, self._resp_guard_ms / 1000.0))
                )
                self.logger.event("response.guard.schedule", delay_ms=int(self._resp_guard_ms))
            except Exception as _e:
                self.logger.event("response.guard.schedule_error", error=str(_e))
            # marker wyjścia OK
            try:
                self.logger.event("commit.exit", status="ok")
            except Exception:
                pass

    async def _handle_ws_message(self, message: str) -> None:
        """Handle incoming WebSocket message."""
        # Dump surowej ramki do pliku (zawsze, dla diagnostyki)
        try:
            with open(RECV_DUMP_PATH, "a") as f:
                f.write(f'{datetime.utcnow().isoformat()}Z {message}\n')
        except Exception:
            # brak dysku? — ignoruj
            pass

        try:
            data = json.loads(message)
            msg_type = data.get("type", "")

            # lekki log typów – tylko wartościowe rzeczy (bez spamu)
            if msg_type.startswith("response.") or msg_type in ("error", "rate_limits.updated", "session.updated"):
                try:
                    self.logger.event("ws.recv", t=msg_type)
                except Exception:
                    pass

            if msg_type == "session.updated":
                self.logger.event("session.ready")

            elif msg_type == "session.created":
                self.logger.event("session.created", session_id=data.get("session", {}).get("id", ""))

            elif msg_type == "input_audio_buffer.speech_started":
                self._publish_ui_state("hearing")
                self.logger.event("speech.started")

            elif msg_type == "input_audio_buffer.speech_stopped":
                self.logger.event("speech.stopped")
                # Commit buffer and request response (serwerowy VAD)
                await self._commit_audio_buffer()
                self._any_audio_since_commit = False

            elif msg_type.startswith("conversation.item.input_audio_transcription"):
                if msg_type == "conversation.item.input_audio_transcription.delta":
                    transcript = data.get("delta", "")
                    if self.stream_cfg.send_partials and transcript:
                        self._publish_partial(transcript)
                elif msg_type == "conversation.item.input_audio_transcription.completed":
                    transcript = data.get("transcript", "")
                    self.logger.event("asr.final", transcript=transcript)

            elif msg_type == "response.created":
                self._publish_ui_state("thinking")
                self._response_pending = False
                self.logger.event("response.created")

                # Record response metrics
                self.metrics.on_response()

            elif msg_type == "response.output_item.added":
                self._publish_ui_state("thinking")

            # ----- TTS STREAM -----
            elif msg_type == "response.output_audio.delta":
                audio_data = decode_audio_from_message(data)
                if audio_data:
                    try:
                        self.tts_player_queue.put(audio_data, block=False)
                        self.logger.event("response.delta", bytes=len(audio_data))

                        # Record TTS metrics
                        self.metrics.on_tts_chunk(len(audio_data))
                    except queue.Full:
                        # Queue full - drop and log
                        self._tts_drops += 1
                        if self._tts_drops % 10 == 1:
                            self.logger.event("tts_queue.full", drops=self._tts_drops)
                        self.metrics.on_audio_drop(1)

            elif msg_type == "response.output_audio.done":
                self.tts_player_queue.put(None)
                self.logger.event("response.done")

            # ----- Backward compatibility (older names) -----
            elif msg_type == "response.audio.delta":
                audio_data = decode_audio_from_message(data)
                if audio_data:
                    try:
                        self.tts_player_queue.put(audio_data, block=False)
                        self.logger.event("response.delta", bytes=len(audio_data), legacy=True)
                    except queue.Full:
                        self._tts_drops += 1
                        if self._tts_drops % 10 == 1:
                            self.logger.event("tts_queue.full", drops=self._tts_drops, legacy=True)

            elif msg_type == "response.audio.done":
                self.tts_player_queue.put(None)
                self.logger.event("response.done", legacy=True)

            # ----- Completed response -----
            elif msg_type in ("response.completed", "response.done"):
                self._publish_ui_state("idle")
                self._completed = True
                self._response_pending = False
                self.logger.event("response.complete")

            elif msg_type == "error":
                error_msg = data.get("error", {}).get("message", "Unknown error")
                self.logger.event("ws.protocol_error", error=error_msg)
                self._publish_error("ws_protocol", error_msg)

            else:
                # Tłumimy szum – drobne, rzadkie typy można podejrzeć w dumpie WS
                pass

        except Exception as e:
            self.logger.event("message_parse_error", error=str(e), sample=message[:200])

    async def _audio_sender_loop(self) -> None:
        """Send audio chunks from queue to WebSocket."""
        while not self.stop_event.is_set() and self.connected:
            try:
                try:
                    chunk = self.audio_queue.get(timeout=0.1)
                    if chunk is None:
                        break
                    await self._send_audio_chunk(chunk)
                except queue.Empty:
                    continue
                except Exception as e:
                    self.logger.event("audio_send_error", error=str(e))
                    break
            except Exception as e:
                self.logger.event("audio_sender_error", error=str(e))
                break

    async def _message_receiver_loop(self) -> None:
        """Receive and handle WebSocket messages."""
        timeouts = 0
        while not self.stop_event.is_set() and self.connected:
            try:
                if not self.websocket:
                    break
                message = await asyncio.wait_for(self.recv(), timeout=1.0)
                timeouts = 0
                await self._handle_ws_message(message)
            except asyncio.TimeoutError:
                timeouts += 1
                # co parę sekund zostaw ślad, że pętla żyje, ale nie ma ramek
                if timeouts % 5 == 0:
                    self.logger.event("ws.recv.timeout", n=timeouts)
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.event("message_recv_error", error=str(e))
                self.connected = False
                break

    # ----- PTT: wątek czytający ENTER -----
    # _ptt_keyboard_thread() comes from StreamingVoicePTTMixin (state.py)

    def _stop_stream_workers(self) -> None:
        """Stop capture/TTS threads and clear queues before reconnect or shutdown."""
        try:
            self.stop_event.set()

            for th_name in ("_capture_thread", "_tts_thread", "_ptt_thread"):
                th = getattr(self, th_name, None)
                if th is not None:
                    try:
                        th.join(timeout=1.0)
                    except Exception:
                        pass
                    setattr(self, th_name, None)

            q = getattr(self, "tts_player_queue", None)
            if q is not None and hasattr(q, "queue"):
                try:
                    with q.mutex:
                        q.queue.clear()
                except Exception:
                    pass

            aq = getattr(self, "audio_queue", None)
            if aq is not None and hasattr(aq, "queue"):
                try:
                    with aq.mutex:
                        aq.queue.clear()
                except Exception:
                    pass

            self.stop_event.clear()
        except Exception as _e:
            self.logger.event("stop_workers_failed", error=_e)

    # _reconnect_loop() is provided by StreamingVoiceTransportMixin (transport.py)

    def _audio_capture_thread(self) -> None:
        """Capture audio and feed to WebSocket queue - delegates to AudioTransmitter."""
        # Sync state from service to transmitter
        self.audio_transmitter.ptt_active = self.ptt_active
        self.audio_transmitter._ptt_was_active = self._ptt_was_active
        self.audio_transmitter._any_audio_since_commit = self._any_audio_since_commit
        self.audio_transmitter.connected = self.connected

        # Delegate to AudioTransmitter
        self.audio_transmitter._audio_capture_thread()

        # Sync state back to service
        self.ptt_active = self.audio_transmitter.ptt_active
        self._ptt_was_active = self.audio_transmitter._ptt_was_active
        self._any_audio_since_commit = self.audio_transmitter._any_audio_since_commit

    def _tts_player_loop(self) -> None:
        """Play TTS audio from queue - delegates to AudioReceiver."""
        # Delegate to AudioReceiver
        self.audio_receiver._tts_player_loop()

    async def _run_session(self) -> None:
        """Run a single WebSocket session."""
        self._loop = asyncio.get_running_loop()

        if not await self._connect():
            return

        # Record connection in metrics
        self.metrics.on_connect()

        # utwórz dump plik z nagłówkiem, by tail/grep nie sypały błędem braku pliku
        try:
            with open(RECV_DUMP_PATH, "a") as f:
                f.write(f"{datetime.utcnow().isoformat()}Z __start_session__ {self.session_id}\n")
        except Exception:
            pass

        await self._send_session_update()

        # Start audio capture thread (jeśli nie wystartował w autostarcie)
        if not (self._capture_thread and self._capture_thread.is_alive()):
            capture_thread = threading.Thread(
                target=self._audio_capture_thread,
                name="voice-stream-capture",
                daemon=True,
            )
            capture_thread.start()
            self._capture_thread = capture_thread

        # Start TTS player thread
        if not (self._tts_thread and self._tts_thread.is_alive()):
            self._tts_thread = threading.Thread(
                target=self._tts_player_loop,
                name="voice-stream-tts",
                daemon=True,
            )
            self._tts_thread.start()

        # Start PTT keyboard thread (tylko jeśli ptt_enabled)
        if self.ptt_enabled and not (self._ptt_thread and self._ptt_thread.is_alive()):
            self._ptt_thread = threading.Thread(
                target=self._ptt_keyboard_thread,
                name="voice-ptt",
                daemon=True,
            )
            self._ptt_thread.start()

        # Run main loops – trzymaj referencje tasków, by móc je anulować
        try:
            self._sender_task = asyncio.create_task(self._audio_sender_loop(), name="audio_sender_loop")
            self._recv_task = asyncio.create_task(self._message_receiver_loop(), name="message_receiver_loop")
            await asyncio.gather(self._sender_task, self._recv_task)
        except Exception as e:
            self.logger.event("session_error", error=str(e))
        finally:
            try:
                if self.websocket:
                    await self.aclose()
            finally:
                self.connected = False
                self._stop_stream_workers()

                # Record disconnection in metrics
                self.metrics.on_disconnect()

    async def _run_with_reconnect(self) -> None:
        """Run WebSocket session with reconnection."""
        while not self.stop_event.is_set():
            try:
                await self._run_session()

                if self.stop_event.is_set():
                    break

                self._stop_stream_workers()
                self._publish_ui_state("idle")

                # Record reconnection attempt in metrics
                self.metrics.on_reconnect()

                if not await self._reconnect_loop():
                    break

            except Exception as e:
                self.logger.event("stream_session_error", error=str(e))
                break

    def listen(self) -> None:
        """Start streaming listen mode."""
        self.logger.event("stream.listen.start")
        self._publish_ui_state("idle")

        try:
            asyncio.run(self._run_with_reconnect())
        except KeyboardInterrupt:
            self.logger.event("stream.listen.interrupted")
        except Exception as e:
            self.logger.event("stream.listen.error", error=str(e))
        finally:
            self.stop()

    def once(self) -> dict[str, Any] | None:
        """Single streaming interaction (duplex, minimal)."""
        self.logger.event("stream.once.start")
        timeout_s = 30
        self._completed = False

        async def single_interaction():
            self._loop = asyncio.get_running_loop()

            if not await self._connect():
                return
            await self._send_session_update()

            if not (self._capture_thread and self._capture_thread.is_alive()):
                try:
                    self._start_capture()
                    self.logger.event("capture.autostart.fallback")
                except Exception as e:
                    self.logger.event("capture.autostart.error", error=str(e))

            if not (self._tts_thread and self._tts_thread.is_alive()):
                self._tts_thread = threading.Thread(
                    target=self._tts_player_loop,
                    name="voice-stream-tts",
                    daemon=True,
                )
                self._tts_thread.start()

            # w „once” też pozwól na PTT (Enter→start/stop)
            if self.ptt_enabled and not (self._ptt_thread and self._ptt_thread.is_alive()):
                self._ptt_thread = threading.Thread(
                    target=self._ptt_keyboard_thread,
                    name="voice-ptt",
                    daemon=True,
                )
                self._ptt_thread.start()

            sender = asyncio.create_task(self._audio_sender_loop())
            receiver = asyncio.create_task(self._message_receiver_loop())

            start = time.time()
            while time.time() - start < timeout_s and not self._completed and self.connected:
                await asyncio.sleep(0.05)

            try:
                sender.cancel()
                receiver.cancel()
            except Exception:
                pass

        try:
            asyncio.run(single_interaction())
            return {"transcript": {"text": "Streaming mode interaction"}, "success": True}
        except Exception as e:
            self.logger.event("stream.once.error", error=str(e))
            return None
        finally:
            self.stop()


# ────────────────────────────────────────────────────────────────────────────
# PROXY/Wrappers dla CLI i testów
# ────────────────────────────────────────────────────────────────────────────
def _run_coro_in_thread(coro) -> Any:
    """Uruchom coroutine w osobnym wątku z własną pętlą (bez kolizji z @pytest.mark.asyncio)."""
    result_box: dict[str, Any] = {}
    error_box: dict[str, BaseException] = {}

    def _target():
        try:
            result_box["r"] = asyncio.run(coro)
        except BaseException as e:  # noqa: BLE001
            error_box["e"] = e

    t = threading.Thread(target=_target, name="svc-stream-proxy", daemon=True)
    t.start()
    t.join()
    if "e" in error_box:
        raise error_box["e"]
    return result_box.get("r")


def run_once_stream(cfg: dict[str, Any], args) -> int:
    """Run streaming once mode (CLI/test proxy)."""
    service = StreamingVoiceService(cfg)
    try:
        # once() jest synchroniczne (wywołuje asyncio.run wewnątrz),
        # ale testowy DummyService.once() może być async → obsłuż oba przypadki.
        ret = service.once()
        if inspect.iscoroutine(ret):
            result = _run_coro_in_thread(ret)
        else:
            result = ret

        if isinstance(result, dict) and result.get("transcript", {}).get("text"):
            print(result["transcript"]["text"])  # noqa: T201
        return 0
    finally:
        aclose = getattr(service, "aclose", None)
        close_sync = getattr(service, "close_sync", None)
        if callable(aclose):
            try:
                _run_coro_in_thread(aclose())
            except Exception:
                pass
        elif callable(close_sync):
            try:
                close_sync()
            except Exception:
                pass


def run_listen_stream(cfg: dict[str, Any], args) -> int:
    """Start streaming in 'listen' mode (CLI/test proxy)."""
    service = StreamingVoiceService(cfg)
    try:
        # listen() jest zwykle synchroniczne (bo samo robi asyncio.run),
        # ale testowy DummyService.listen() bywa async → obsłuż oba przypadki.
        ret = service.listen()
        if inspect.iscoroutine(ret):
            _run_coro_in_thread(ret)  # DummyService.listen() jest async w teście
        return 0
    finally:
        aclose = getattr(service, "aclose", None)
        close_sync = getattr(service, "close_sync", None)
        if callable(aclose):
            try:
                _run_coro_in_thread(aclose())
            except Exception:
                pass
        elif callable(close_sync):
            try:
                close_sync()
            except Exception:
                pass


def run_ptt_stream(cfg: dict[str, Any], args) -> int:
    """PTT: włącz hotword.enabled i deleguj do run_listen_stream (test patchuje ten symbol)."""
    cfg2 = dict(cfg) if cfg else {}
    hot = dict(cfg2.get("hotword", {}))
    hot["enabled"] = True
    hot["engine"] = "ptt"
    cfg2["hotword"] = hot
    return run_listen_stream(cfg2, args)


# ────────────────────────────────────────────────────────────────────────────
# Re-exports from extracted modules (for API compatibility)
# ────────────────────────────────────────────────────────────────────────────
# Main class StreamingVoiceService is defined above and remains the primary export
# Transport mixin: StreamingVoiceTransportMixin (imported above)
# PTT state mixin: StreamingVoicePTTMixin (imported above)
# Audio chunks: AudioChunkProcessor (imported above)
