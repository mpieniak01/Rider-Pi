# apps/voice/stream/services.py
"""Refactored streaming voice service using transport and state modules.

This is a streamlined version of the original streaming service,
focusing on orchestration while delegating transport and state management.
"""

from __future__ import annotations

import asyncio
import base64
import json
import queue
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from .. import voice_logging
from ..common import ensure_event_logger
from ..svc_audio import capture_continuous
from ..utils import run_sync  # ⬅️ bezpieczne uruchamianie coroutine z kodu sync
from .state import PTTEvent, PTTState, PTTStateMachine
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


class StreamingVoiceService:
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

        # Worker threads
        self._capture_thread: threading.Thread | None = None
        self._tts_player_thread: threading.Thread | None = None
        self._message_handler_task: asyncio.Task[None] | None = None

        # Session state
        self.session_id: str = ""
        self.partial_transcript = ""
        self._completed: bool = False

        # PTT configuration
        hotword_cfg = self.config.get("hotword", {})
        self.ptt_enabled: bool = str(hotword_cfg.get("engine", "")).lower() == "ptt"
        self._any_audio_since_commit: bool = False

        # event loop (do bezpiecznych zamknięć z kodu synchronicznego)
        self._loop: asyncio.AbstractEventLoop | None = None

    # ──────────────────────────────────────────────────────────────────────────
    # PTT state

    def _setup_state_callbacks(self) -> None:
        """Setup PTT state machine callbacks."""
        self.ptt_state.add_enter_callback(PTTState.ARMING, self._on_arming)
        self.ptt_state.add_enter_callback(PTTState.RECORDING, self._on_recording_start)
        self.ptt_state.add_enter_callback(PTTState.SPEAKING, self._on_speaking_start)
        self.ptt_state.add_transition_callback(PTTState.COMMIT, PTTState.WAIT_REPLY, self._on_commit_complete)

    def _on_arming(self) -> None:
        self._publish_ui_state("arming")
        # TODO: optional beep here

    def _on_recording_start(self) -> None:
        self._publish_ui_state("recording")
        self._any_audio_since_commit = False

    def _on_speaking_start(self) -> None:
        self._publish_ui_state("speaking")

    def _on_commit_complete(self, event: PTTEvent) -> None:
        self._publish_ui_state("processing")

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
            return True
        except Exception as e:
            self.logger.event("transport.init.error", error=str(e))
            return False

    def _get_auth_header(self) -> str:
        """Extract API key from auth config."""
        auth = self.stream_cfg.auth
        if auth.startswith("env:"):
            import os

            env_key = auth[4:]
            api_key = (os.environ.get(env_key, "") or "").strip()
            if not api_key:
                self.logger.event("auth_missing_key", env_var=env_key)
                raise RuntimeError(f"Missing environment variable: {env_key}")
            return api_key
        return auth.strip()

    async def _send_session_init(self) -> None:
        """Send session initialization message."""
        if not self.transport:
            return

        self.session_id = str(uuid.uuid4())
        init_message = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "voice": "verse",
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "turn_detection": {"type": "server_vad"} if self.stream_cfg.server_vad else None,
            },
        }
        await self.transport.send(json.dumps(init_message))
        self.logger.event("session.init", session_id=self.session_id)

    # ──────────────────────────────────────────────────────────────────────────
    # UI publish

    def _publish_ui_state(self, state: str) -> None:
        if self.ui_publisher:
            try:
                self.ui_publisher.publish("ui.state", {"state": state, "ts": time.time()})
            except Exception as e:
                self.logger.event("ui_state_pub_error", error=str(e))

    def _publish_partial(self, text: str) -> None:
        if self.ui_publisher and text != self.partial_transcript:
            self.partial_transcript = text
            try:
                self.ui_publisher.publish("ui.partial", {"text": text, "ts": time.time()})
            except Exception as e:
                self.logger.event("partial_pub_error", error=str(e))

    def _publish_error(self, error_type: str, message: str) -> None:
        if self.ui_publisher:
            try:
                self.ui_publisher.publish("ui.error", {"type": error_type, "message": message, "ts": time.time()})
            except Exception as e:
                self.logger.event("error_pub_error", error=str(e))

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
            self._start_audio_capture()
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
        # wyczyść kolejki audio → zakończ TTS
        try:
            self.tts_player_queue.put_nowait(None)
        except Exception:
            pass
        # zaplanuj asynchroniczne sprzątanie jeśli mamy loop; w innym razie domknij natychmiast
        if self._loop:
            try:
                asyncio.run_coroutine_threadsafe(self._cleanup(), self._loop)
            except Exception as e:
                self.logger.event("stream.stop.cleanup_schedule_error", error=str(e))
        else:
            try:
                run_sync(self._cleanup())
            except Exception as e:
                self.logger.event("stream.stop.cleanup_sync_error", error=str(e))

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
        self._message_handler_task = asyncio.create_task(self._message_handler_loop())

        while not self.stop_event.is_set() and self.transport:
            await asyncio.sleep(0.1)  # prevent busy loop
            if self.ptt_enabled:
                # integrate keyboard PTT here if needed
                pass

    # ──────────────────────────────────────────────────────────────────────────
    # Messaging

    async def _message_handler_loop(self) -> None:
        """Handle incoming WebSocket messages."""
        while not self.stop_event.is_set() and self.transport:
            try:
                message = await asyncio.wait_for(self.transport.recv(), timeout=1.0)
                await self._handle_message(message)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self.logger.event("message_recv_error", error=str(e))
                break

    async def _handle_message(self, message: str) -> None:
        """Handle incoming WebSocket message."""
        try:
            data = json.loads(message)
            msg_type = data.get("type", "")

            if msg_type == "response.audio.delta":
                audio_b64 = data.get("delta", "")
                if audio_b64:
                    audio_data = base64.b64decode(audio_b64)
                    self.tts_player_queue.put(audio_data)

            elif msg_type == "response.audio.done":
                self.tts_player_queue.put(None)
                self.ptt_state.transition(PTTEvent.TTS_COMPLETE)

            elif msg_type == "response.text.delta":
                text = data.get("delta", "")
                self._publish_partial(text)

            elif msg_type in ("response.completed", "response.done"):
                self._completed = True
                self.ptt_state.transition(PTTEvent.TTS_COMPLETE)

            elif msg_type == "error":
                error_msg = data.get("error", {}).get("message", "Unknown error")
                self.logger.event("ws.protocol_error", error=error_msg)
                self._publish_error("ws_protocol", error_msg)
                self.ptt_state.transition(PTTEvent.ERROR)

        except Exception as e:
            self.logger.event("message_parse_error", error=str(e), sample=message[:200])

    # ──────────────────────────────────────────────────────────────────────────
    # Workers

    def _start_audio_capture(self) -> None:
        """Start audio capture thread (generator → queue)."""
        if self._capture_thread and self._capture_thread.is_alive():
            return

        # policz bajty na chunk
        cap_cfg = self.config.get("capture", {}) or {}
        sr = int(cap_cfg.get("sample_rate", self.stream_cfg.sample_rate))
        chunk_ms = int(self.stream_cfg.chunk_ms)
        chunk_size = int(sr * chunk_ms / 1000) * 2  # S16_LE mono (downmix w transporcie/serwerze)

        def capture_target():
            try:
                for chunk in capture_continuous(cap_cfg, chunk_size):
                    if self.stop_event.is_set():
                        break
                    # barge-in: wyczyść TTS, jeśli aktywny
                    if self.barge_in_event.is_set():
                        while not self.tts_player_queue.empty():
                            try:
                                _ = self.tts_player_queue.get_nowait()
                            except queue.Empty:
                                break
                        self.barge_in_event.clear()
                    self.audio_queue.put(chunk)
            except Exception as e:
                self.logger.event("capture_thread_error", error=str(e))
            finally:
                # sygnał EOF do pętli sendera
                try:
                    self.audio_queue.put_nowait(None)
                except Exception:
                    pass

        self._capture_thread = threading.Thread(target=capture_target, name="stream-capture", daemon=True)
        self._capture_thread.start()

    def _start_tts_player(self) -> None:
        """Start TTS player thread."""
        if self._tts_player_thread and self._tts_player_thread.is_alive():
            return

        def player_target():
            from ..audio.playback import PlaybackConfig, start_stream

            stream = None
            try:
                playback_cfg = PlaybackConfig(**self.config.get("playback", {}))
                while not self.stop_event.is_set():
                    try:
                        chunk = self.tts_player_queue.get(timeout=1.0)
                    except queue.Empty:
                        continue

                    if chunk is None:
                        if stream:
                            try:
                                stream.close()
                            except Exception as e:
                                self.logger.event("tts.stream.close_error", error=str(e))
                            stream = None
                        continue

                    if stream is None:
                        try:
                            stream = start_stream("pcm16", playback_cfg, self.logger)
                            self.ptt_state.transition(PTTEvent.TTS_START)
                        except Exception as e:
                            self.logger.event("tts.stream.start_error", error=str(e))
                            stream = None

                    if stream:
                        try:
                            stream.write(chunk)
                        except Exception as e:
                            self.logger.event("tts.stream.write_error", error=str(e))
                            try:
                                stream.close()
                            except Exception:
                                pass
                            stream = None
            except Exception as e:
                self.logger.event("tts_player_thread_error", error=str(e))
            finally:
                if stream:
                    import contextlib

                    with contextlib.suppress(Exception):
                        stream.close()

        self._tts_player_thread = threading.Thread(target=player_target, name="stream-tts-player", daemon=True)
        self._tts_player_thread.start()

    # ──────────────────────────────────────────────────────────────────────────
    # Cleanup

    def _cleanup_workers(self) -> None:
        """Clean up worker threads."""
        if not self.stop_event.is_set():
            self.stop_event.set()

        # wyślij sentinele
        for q in (self.audio_queue, self.tts_player_queue):
            try:
                q.put_nowait(None)
            except Exception:
                pass

        for t in (self._capture_thread, self._tts_player_thread):
            if t and t.is_alive():
                try:
                    t.join(timeout=1.5)
                except Exception:
                    pass

        self._capture_thread = None
        self._tts_player_thread = None

    async def _cleanup(self) -> None:
        """Full cleanup including transport."""
        # cancel message handler
        if self._message_handler_task and not self._message_handler_task.done():
            self._message_handler_task.cancel()
            try:
                await self._message_handler_task
            except asyncio.CancelledError:
                pass
            finally:
                self._message_handler_task = None

        # close transport
        if self.transport:
            try:
                await self.transport.close()
            except Exception as e:
                self.logger.event("transport.close.error", error=str(e))
            finally:
                self.transport = None

        # workers & state
        self._cleanup_workers()
        self.ptt_state.reset()
        self._publish_ui_state("idle")

    # ──────────────────────────────────────────────────────────────────────────
    # Waiters

    async def _wait_for_completion(self) -> None:
        """Wait for interaction completion."""
        while not self._completed and not self.stop_event.is_set():
            await asyncio.sleep(0.1)
