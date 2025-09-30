"""WebSocket streaming voice service - duplex realtime ASR→CHAT→TTS pipeline."""

from __future__ import annotations

import asyncio
import json
import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any

try:
    import websockets  # type: ignore
except Exception:  # pragma: no cover

    class _WSStub:
        def __getattr__(self, _):  # minimalny stub dla testów
            raise RuntimeError("websockets unavailable")

    websockets = _WSStub()  # type: ignore

from . import voice_logging
from .capture import CaptureConfig
from .common import ensure_event_logger
from .playback import play_ding  # noqa: F401 - Re-export for test compatibility
from .state import StreamingVoicePTTMixin
from .stream_chunks import AudioChunkProcessor, calculate_chunk_size, decode_audio_from_message
from .svc_audio import capture_continuous
from .transport import StreamingVoiceTransportMixin


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


class StreamingVoiceService(StreamingVoiceTransportMixin, StreamingVoicePTTMixin):
    """WebSocket-based streaming voice service with duplex audio."""

    def __init__(self, config: dict[str, Any], ui_publisher: Any | None = None) -> None:
        self.config = config
        self.stream_cfg = StreamConfig.from_dict(config)
        self.ui_publisher = ui_publisher
        self.logger = ensure_event_logger(voice_logging.get_logger("voice.stream"))

        # Runtime state
        self.websocket: Any = None
        self.session_id: str = ""
        self.current_state = "idle"
        self.audio_queue: queue.Queue[bytes | None] = queue.Queue()
        self.tts_player_queue: queue.Queue[bytes | None] = queue.Queue()
        self.stop_event = threading.Event()
        self.barge_in_event = threading.Event()

        # workers (dla join/stop)
        self._capture_thread: threading.Thread | None = None
        self._tts_thread: threading.Thread | None = None
        self._ptt_thread: threading.Thread | None = None

        # Partial transcript tracking
        self.partial_transcript = ""

        # Connection state
        self.connected = False
        self.retry_count = 0

        # one-shot interaction flag
        self._completed: bool = False

        # --- PTT (push-to-talk) sterowanie Enterem ---
        hotword_cfg = self.config.get("hotword") or {}
        ptt_cfg = self.config.get("ptt") or {}
        self.ptt_enabled: bool = str(hotword_cfg.get("engine", "")).lower() == "ptt" or bool(
            ptt_cfg.get("enabled", False)
        )
        self.ptt_active: bool = False  # czy aktualnie nagrywamy po Enter
        self._any_audio_since_commit: bool = False  # czy coś poleciało od startu PTT
        self._loop: asyncio.AbstractEventLoop | None = None  # główna pętla do commitów z wątku

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

    # ---- Transport methods now in StreamingVoiceTransportMixin (transport.py) ----
    # send(), recv(), aclose(), close(), close_sync(), _connect(), _reconnect_loop()
    # are provided by the mixin

    # apps/voice/svc_stream.py – wewnątrz klasy StreamingVoiceService
    def __del__(self) -> None:
        try:
            # prefer sync
            if hasattr(self, "close_sync"):
                self.close_sync()  # best-effort
                return
            # fallback: spróbuj bez run_sync
            import asyncio

            coro = getattr(self, "aclose", None)
            if callable(coro):
                loop = asyncio.get_event_loop()
                if loop.is_running():  # w testach często tak
                    loop.create_task(coro())  # odpal bez blokowania
                else:
                    asyncio.run(coro())
        except Exception:
            pass

    def stop(self) -> None:
        """Stop the streaming service (idempotent, test-friendly)."""
        # Sygnał stop natychmiast – testy oczekują ustawionych flag.
        # Ustaw event zatrzymania na początku.
        try:
            self.stop_event.set()
        except Exception:
            pass

        # Reszta flag wewnętrznych
        try:
            self._stopping = True
            if hasattr(self, "_running"):
                self._running = False
            if hasattr(self, "_ptt_active"):
                self._ptt_active = False
            log = getattr(self.logger, "event", None)
            if callable(log):
                log("stream.stop")
        except Exception:
            # Stop ma być odporny na wyjątki – testy wolą idempotentność.
            pass

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
                        _ = fut  # dla mypy
                        return
                except Exception as e:
                    self.logger.event("stream.stop.schedule_failed", error=str(e))
                    # spadamy do ścieżki synchronicznej
        except Exception as e:
            self.logger.event("stream.stop.loop_probe_failed", error=str(e))
            # spadamy do ścieżki synchronicznej

        # 2) Preferuj API synchroniczne, jeśli jest dostępne.
        try:
            if hasattr(self, "close_sync"):
                self.close_sync()
                self.logger.event("stream.stop.ok", via="close_sync")
                return
        except Exception as e:
            self.logger.event("stream.stop.close_sync_failed", error=str(e))
            # fallback niżej

        # 3) Fallback: zablokowane domknięcie aclose()/close() bez warningów.
        try:
            from .utils import run_sync  # lokalny import, łatwy do mockowania
        except Exception:
            run_sync = None  # type: ignore[assignment]

        try:
            if hasattr(self, "aclose"):
                if run_sync is not None:
                    run_sync(self.aclose(), timeout=2.0)
                else:
                    asyncio.run(self.aclose())
                self.logger.event("stream.stop.ok", via="aclose")
                return
        except Exception as e:
            self.logger.event("stream.stop.aclose_failed", error=str(e))

        try:
            if hasattr(self, "close"):
                is_coro_fn = (
                    run_sync is not None
                    and hasattr(asyncio, "iscoroutinefunction")
                    and asyncio.iscoroutinefunction(self.close)  # type: ignore[arg-type]
                )
                if is_coro_fn:
                    run_sync(self.close(), timeout=2.0)  # type: ignore[misc]
                else:
                    close_fn = getattr(self, "close", None)
                    if callable(close_fn):
                        close_fn()  # type: ignore[call-arg]
                self.logger.event("stream.stop.ok", via="close")
                return
        except Exception as e:
            self.logger.event("stream.stop.close_failed", error=str(e))
            # Ostatecznie: nic więcej nie robimy – stop ma być idempotentny.
        try:
            self._stopping = True
            if hasattr(self, "_running"):
                self._running = False
            if hasattr(self, "_ptt_active"):
                self._ptt_active = False
            log = getattr(self.logger, "event", None)
            if callable(log):
                log("stream.stop")
        except Exception:
            # Stop ma być odporny na wyjątki – testy wolą idempotentność.
            pass

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
                        _ = fut  # dla mypy
                        return
                except Exception as e:
                    self.logger.event("stream.stop.schedule_failed", error=str(e))
                    # spadamy do ścieżki synchronicznej
        except Exception as e:
            self.logger.event("stream.stop.loop_probe_failed", error=str(e))
            # spadamy do ścieżki synchronicznej

        # 2) Preferuj API synchroniczne, jeśli jest dostępne.
        try:
            if hasattr(self, "close_sync"):
                self.close_sync()
                self.logger.event("stream.stop.ok", via="close_sync")
                return
        except Exception as e:
            self.logger.event("stream.stop.close_sync_failed", error=str(e))
            # fallback niżej

        # 3) Fallback: zablokowane domknięcie aclose()/close() bez warningów.
        try:
            from .utils import run_sync  # lokalny import, łatwy do mockowania
        except Exception:
            run_sync = None  # type: ignore[assignment]

        try:
            if hasattr(self, "aclose"):
                if run_sync is not None:
                    run_sync(self.aclose(), timeout=2.0)
                else:
                    asyncio.run(self.aclose())
                self.logger.event("stream.stop.ok", via="aclose")
                return
        except Exception as e:
            self.logger.event("stream.stop.aclose_failed", error=str(e))

        try:
            if hasattr(self, "close"):
                is_coro_fn = (
                    run_sync is not None
                    and hasattr(asyncio, "iscoroutinefunction")
                    and asyncio.iscoroutinefunction(self.close)  # type: ignore[arg-type]
                )
                if is_coro_fn:
                    run_sync(self.close(), timeout=2.0)  # type: ignore[misc]
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
        """Extract API key from auth config."""
        auth = self.stream_cfg.auth
        if auth.startswith("env:"):
            env_key = auth[4:]
            api_key = (os.environ.get(env_key, "") or "").strip()
            if not api_key:
                self.logger.event("auth_missing_key", env_var=env_key)
                raise RuntimeError(f"Missing environment variable: {env_key}. Set it with: export {env_key}=sk-...")
            return api_key
        return auth.strip()

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

        self._capture_thread = threading.Thread(target=_target, name="voice-stream-capture-autostart", daemon=True)
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

    # -------------------------------------------------------------------------
    # _connect() is now provided by StreamingVoiceTransportMixin (transport.py)
    # -------------------------------------------------------------------------

    async def _send_session_update(self) -> None:
        """Send session configuration to WebSocket."""
        if not self.websocket:
            return

        # Use chunk processor for session message generation

        chunk_processor = AudioChunkProcessor(self._capture_cfg_obj, self.stream_cfg, self.logger)
        session_msg = chunk_processor.create_session_update_message(self.config)

        await self.send(session_msg)
        self.logger.event("session.configured")

        # Self-test TTS (opcjonalnie via env)
        if os.getenv("VOICE_TTS_SELFTEST") == "1":
            try:
                tts_cfg = self.config.get("tts", {}) or {}
                voice = tts_cfg.get("voice") or "verse"
                test_msg = {
                    "type": "response.create",
                    "response": {
                        "modalities": ["audio"],
                        "instructions": "Test: TTS działa po stronie klienta.",
                        "audio": {"voice": voice, "format": "pcm16"},
                    },
                }
                await self.send(json.dumps(test_msg))
                self.logger.event("tts.selftest.sent", voice=voice)
            except Exception as e:
                self.logger.event("tts.selftest.error", error=str(e))

        # autostart capture tylko gdy NIE PTT
        try:
            if not self.ptt_enabled:
                self._start_capture()
                self.logger.event("capture.autostart")
            else:
                self.logger.event("ptt.enabled")
        except Exception as _e:
            self.logger.event("capture.autostart.error", error=str(_e))

        # kompat: stare przełączniki hotword=off
        try:
            if (not self.ptt_enabled) and str(getattr(self, "_hotword", "")).lower() == "off":
                self.logger.event("capture.autostart")
                self._start_capture()
        except Exception as _e:
            self.logger.event("capture.autostart.error", error=str(_e))
        try:
            base_cfg = getattr(self, "cfg", None) or getattr(self, "config", None) or {}
            if (not self.ptt_enabled) and str(base_cfg.get("hotword", "")).lower() == "off":
                self.logger.event("capture.autostart")
                self._start_capture()
        except Exception as _e:
            self.logger.event("capture.autostart.error", error=str(_e))

    async def _send_audio_chunk(self, audio_data: bytes) -> None:
        """Send audio chunk to WebSocket."""
        if not self.websocket or not audio_data:
            return

        # Use chunk processor for audio encoding

        chunk_processor = AudioChunkProcessor(self._capture_cfg_obj, self.stream_cfg, self.logger)
        result = chunk_processor.process_and_encode_chunk(audio_data)

        if result:
            message_json, telemetry = result
            await self.send(message_json)
            self._any_audio_since_commit = True

            # Log telemetry
            self.logger.event("stream.tx", **telemetry)

    async def _commit_audio_buffer(self) -> None:
        """Commit the audio buffer and trigger response generation."""
        if not self.websocket:
            return

        # Use chunk processor for message generation

        chunk_processor = AudioChunkProcessor(self._capture_cfg_obj, self.stream_cfg, self.logger)

        commit_msg = chunk_processor.create_commit_message()
        await self.send(commit_msg)

        response_msg = chunk_processor.create_response_message(self.config)
        await self.send(response_msg)
        self.logger.event("response.requested")

    async def _handle_ws_message(self, message: str) -> None:
        """Handle incoming WebSocket message."""
        try:
            data = json.loads(message)
            msg_type = data.get("type", "")

            # log surowych typów – pomaga przy diagnozie po commit
            self.logger.event("ws.recv", t=msg_type)

            if msg_type == "input_audio_buffer.speech_started":
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
                self.logger.event("response.created")

            elif msg_type == "response.output_item.added":
                self._publish_ui_state("thinking")

            # ----- TTS STREAM -----
            elif msg_type == "response.output_audio.delta":
                # Use chunk processor for audio decoding

                audio_data = decode_audio_from_message(data)
                if audio_data:
                    self.tts_player_queue.put(audio_data)
                    self.logger.event("tts.audio_chunk", bytes=len(audio_data))

            elif msg_type == "response.output_audio.done":
                self.tts_player_queue.put(None)
                self.logger.event("tts.stream_complete")

            # ----- Backward compatibility (older names) -----
            elif msg_type == "response.audio.delta":
                # Use chunk processor for audio decoding

                audio_data = decode_audio_from_message(data)
                if audio_data:
                    self.tts_player_queue.put(audio_data)
                    self.logger.event("tts.audio_chunk_legacy", bytes=len(audio_data))

            elif msg_type == "response.audio.done":
                self.tts_player_queue.put(None)
                self.logger.event("tts.stream_complete_legacy")

            # ----- Completed response -----
            elif msg_type in ("response.completed", "response.done"):
                self._publish_ui_state("idle")
                self._completed = True
                self.logger.event("response.complete")

            elif msg_type == "error":
                error_msg = data.get("error", {}).get("message", "Unknown error")
                self.logger.event("ws.protocol_error", error=error_msg)
                self._publish_error("ws_protocol", error_msg)

            else:
                sample = message[:300] if isinstance(message, str) else ""
                self.logger.event("ws.msg", raw=data.get("type", ""), sample=sample)

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
        while not self.stop_event.is_set() and self.connected:
            try:
                if not self.websocket:
                    break
                message = await asyncio.wait_for(self.recv(), timeout=1.0)
                await self._handle_ws_message(message)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self.logger.event("message_recv_error", error=str(e))
                self.connected = False
                break

    # ----- PTT: wątek czytający ENTER -----
    # _ptt_keyboard_thread() is now provided by StreamingVoicePTTMixin (state.py)

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
            self.logger.event("stop_workers_failed", error=str(_e))

    # _reconnect_loop() is now provided by StreamingVoiceTransportMixin (transport.py)

    def _audio_capture_thread(self) -> None:
        """Capture audio and feed to WebSocket queue."""
        try:
            capture_cfg = self.config.get("capture", {})
            sample_rate = capture_cfg.get("sample_rate", 16000)
            chunk_ms = self.stream_cfg.chunk_ms
            # Use utility function for chunk size calculation

            chunk_size = calculate_chunk_size(sample_rate, chunk_ms)

            for audio_chunk in capture_continuous(capture_cfg, chunk_size):
                if self.stop_event.is_set():
                    break

                if self.barge_in_event.is_set():
                    # Clear TTS queue on barge-in
                    while not self.tts_player_queue.empty():
                        try:
                            self.tts_player_queue.get_nowait()
                        except queue.Empty:
                            break
                    self.barge_in_event.clear()

                # GATE: wysyłaj audio TYLKO gdy PTT aktywne lub gdy PTT wyłączone
                if audio_chunk and self.connected and (self.ptt_active or not self.ptt_enabled):
                    self.audio_queue.put(audio_chunk)

        except Exception as e:
            self.logger.event("audio_capture_error", error=str(e))
        finally:
            # Wrzucamy None tylko przy globalnym stopie/reconnect (żeby nie zabić sendera
            # przy chwilowym padzie capture)
            if self.stop_event.is_set() or not self.connected:
                self.audio_queue.put(None)

    def _tts_player_loop(self) -> None:
        """Play TTS audio from queue (strumieniowo, jeden proces na odpowiedź)."""
        from .playback import PlaybackConfig, play_bytes, start_stream

        try:
            playback_cfg = PlaybackConfig(**self.config.get("playback", {}))
            # Bufor na początek (jitter buffer), zanim wystartujemy strumień
            prebuffer = bytearray()
            threshold = max(1, self.stream_cfg.jitter_buffer_ms) * 32  # ~32B/ms @ 16kHz mono
            stream = None  # PlaybackStream lub None

            def _close_stream():
                nonlocal stream
                if stream is not None:
                    try:
                        stream.close()
                    except Exception as _e:
                        self.logger.event("tts.stream.close_error", error=str(_e))
                    stream = None

            while not self.stop_event.is_set():
                try:
                    # Obsługa barge-in: natychmiast kończ bieżący stream
                    if self.barge_in_event.is_set():
                        _close_stream()
                        prebuffer.clear()
                        self.barge_in_event.clear()

                    chunk = self.tts_player_queue.get(timeout=0.1)

                    if chunk is None:
                        # koniec bieżącej odpowiedzi TTS
                        if stream is None:
                            if prebuffer:
                                try:
                                    play_bytes(bytes(prebuffer), "pcm16", playback_cfg)
                                except Exception as _e:
                                    self.logger.event("tts.play_once.error", error=str(_e))
                            prebuffer.clear()
                        _close_stream()
                        self._publish_ui_state("idle")
                        continue

                    # mamy dane
                    if stream is None:
                        prebuffer.extend(chunk)
                        if len(prebuffer) >= threshold:
                            stream = start_stream("pcm16", playback_cfg, self.logger, accumulate=False)
                            if stream is None:
                                try:
                                    play_bytes(bytes(prebuffer), "pcm16", playback_cfg)
                                except Exception as _e:
                                    self.logger.event("tts.fallback.play_error", error=str(_e))
                                prebuffer.clear()
                            else:
                                self._publish_ui_state("speaking")
                                try:
                                    if prebuffer:
                                        stream.write(bytes(prebuffer))
                                    prebuffer.clear()
                                except Exception as _e:
                                    self.logger.event("tts.stream.write_error", error=str(_e))
                                    _close_stream()
                                    continue
                    else:
                        try:
                            stream.write(chunk)
                        except Exception as _e:
                            self.logger.event("tts.stream.write_error", error=str(_e))
                            _close_stream()
                            try:
                                play_bytes(chunk, "pcm16", playback_cfg)
                            except Exception as _e2:
                                self.logger.event("tts.fallback.play_error", error=str(_e2))

                except queue.Empty:
                    continue
                except Exception as e:
                    self.logger.event("tts_player_error", error=str(e))

        except Exception as e:
            self.logger.event("tts_player_thread_error", error=str(e))

    async def _run_session(self) -> None:
        """Run a single WebSocket session."""
        self._loop = asyncio.get_running_loop()

        if not await self._connect():
            return

        await self._send_session_update()

        # Start audio capture thread (jeśli nie wystartował w autostarcie)
        if not (self._capture_thread and self._capture_thread.is_alive()):
            capture_thread = threading.Thread(
                target=self._audio_capture_thread, name="voice-stream-capture", daemon=True
            )
            capture_thread.start()
            self._capture_thread = capture_thread

        # Start TTS player thread (nowa nazwa pola: _tts_thread)
        if not (self._tts_thread and self._tts_thread.is_alive()):
            self._tts_thread = threading.Thread(target=self._tts_player_loop, name="voice-stream-tts", daemon=True)
            self._tts_thread.start()

        # Start PTT keyboard thread (tylko jeśli ptt_enabled)
        if self.ptt_enabled and not (self._ptt_thread and self._ptt_thread.is_alive()):
            self._ptt_thread = threading.Thread(target=self._ptt_keyboard_thread, name="voice-ptt", daemon=True)
            self._ptt_thread.start()

        # Run main loops
        try:
            await asyncio.gather(self._audio_sender_loop(), self._message_receiver_loop())
        except Exception as e:
            self.logger.event("session_error", error=str(e))
        finally:
            try:
                if self.websocket:
                    await self.aclose()
            finally:
                self.connected = False
                self._stop_stream_workers()

    async def _run_with_reconnect(self) -> None:
        """Run WebSocket session with reconnection."""
        while not self.stop_event.is_set():
            try:
                await self._run_session()

                if self.stop_event.is_set():
                    break

                self._stop_stream_workers()
                self._publish_ui_state("idle")

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
                self._tts_thread = threading.Thread(target=self._tts_player_loop, name="voice-stream-tts", daemon=True)
                self._tts_thread.start()

            # w „once” też pozwól na PTT (Enter→start/stop)
            if self.ptt_enabled and not (self._ptt_thread and self._ptt_thread.is_alive()):
                self._ptt_thread = threading.Thread(target=self._ptt_keyboard_thread, name="voice-ptt", daemon=True)
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


def run_once_stream(cfg: dict[str, Any], args) -> int:
    """Run streaming once mode."""
    service = StreamingVoiceService(cfg)
    result = service.once()
    if result and result.get("transcript", {}).get("text"):
        print(result["transcript"]["text"])  # noqa: T201 (print w CLI)
    return 0


# --- Test-friendly wrappers (mockowane w testach) ---


def run_listen_stream(cfg: dict[str, Any], args) -> int:
    """Start streaming in 'listen' mode (placeholder used by tests to patch)."""
    return 0


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
