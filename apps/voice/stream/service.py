# apps/voice/stream/services.py
"""Refactored streaming voice service using transport and state modules.

This is a streamlined version of the original streaming service,
focusing on orchestration while delegating transport and state management.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass, fields
from typing import Any

from .. import voice_logging
from ..capture import CaptureConfig
from ..common import ensure_event_logger
from ..rt_protocol import build_audio_commit, build_response_create
from ..session_prefs import build_session_preferences, session_prefs_to_dict
from ..stream_chunks import AudioChunkProcessor
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
        self._audio_sender_task: asyncio.Task[None] | None = None

        # Session state
        self.session_id: str = ""
        self.partial_transcript = ""
        self._completed: bool = False
        self._session_prefs: Any | None = None
        self._commit_lock = asyncio.Lock()
        self._chunk_counter = 0

        # Capture configuration for chunk processing
        capture_in = dict(self.config.get("capture", {}) or {})
        capture_filtered = capture_in
        try:
            valid_fields = {field.name for field in fields(CaptureConfig)}
            capture_filtered = {k: v for k, v in capture_in.items() if k in valid_fields}
            self._capture_cfg = CaptureConfig(**capture_filtered)
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
        self._chunk_processor = AudioChunkProcessor(self._capture_cfg, self.stream_cfg, self.logger)

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

    def _get_auth_header(self) -> str:
        """Extract API key from auth config following security best practices."""

        def _expand(path: str) -> str:
            return os.path.expanduser(os.path.expandvars(path))

        auth = (self.stream_cfg.auth or "").strip()

        if auth.startswith("env:"):
            env_key = auth[4:]
            api_key = (os.environ.get(env_key, "") or "").strip()
            if not api_key:
                self.logger.event("auth_missing_key", env_var=env_key)
                raise RuntimeError(f"Missing environment variable: {env_key}")
            self.logger.event("auth.loaded", src="env", var=env_key, length=len(api_key))
            return api_key

        if auth.startswith("file:"):
            path = _expand(auth[5:])
            try:
                with open(path, encoding="utf-8") as handle:
                    key = handle.read().strip()
            except FileNotFoundError as exc:
                self.logger.event("auth_file_missing", path=path)
                raise RuntimeError(f"API key file not found: {path}") from exc
            if not key:
                raise RuntimeError(f"API key file empty: {path}")
            self.logger.event("auth.loaded", src="file", length=len(key))
            return key

        if auth.startswith("bashenv:"):
            # Historical scheme removed for security reasons to avoid sourcing shell profiles.
            self.logger.event("auth_bashenv_rejected", scheme="bashenv")
            raise RuntimeError(
                "bashenv: scheme is no longer supported. Use env:VARNAME or file:/path/to/keyfile instead."
            )

        if auth:
            return auth

        fallback = (os.environ.get("OPENAI_API_KEY", "") or "").strip()
        if fallback:
            self.logger.event("auth.loaded", src="env", var="OPENAI_API_KEY", length=len(fallback))
            return fallback

        raise RuntimeError("Missing OpenAI API key. Configure stream.auth or set OPENAI_API_KEY.")

    async def _send_session_init(self) -> None:
        """Send session initialization message."""
        if not self.transport:
            return

        self.session_id = str(uuid.uuid4())
        prefs = build_session_preferences(self.config, stream_cfg=self.stream_cfg)
        self._session_prefs = prefs
        session_payload = session_prefs_to_dict(prefs)

        init_message = {"type": "session.update", "session": session_payload}

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
        self._audio_sender_task = asyncio.create_task(self._audio_sender_loop())
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

            elif msg_type == "response.created":
                self.logger.event("response.created")
                self.ptt_state.transition(PTTEvent.SERVER_RESPONSE)

            elif msg_type == "session.updated":
                self.logger.event("session.updated")

            elif msg_type == "input_audio_buffer.speech_started":
                self.logger.event("speech.started")
                self.ptt_state.transition(PTTEvent.VOICE_START)

            elif msg_type == "input_audio_buffer.speech_stopped":
                self.logger.event("speech.stopped")
                self.ptt_state.transition(PTTEvent.VOICE_END)
                await self._commit_audio_buffer()

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

    async def _audio_sender_loop(self) -> None:
        """Send captured audio frames to the realtime API."""
        self.logger.event("audio.sender.start")
        try:
            while not self.stop_event.is_set():
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
        """Encode and send a PCM16 chunk to the server."""
        if not chunk or not self.transport:
            return

        try:
            result = self._chunk_processor.process_and_encode_chunk(chunk)
            if not result:
                return

            message_json, telemetry = result
            await self.transport.send(message_json)
            self._chunk_counter += 1
            self._any_audio_since_commit = True

            if self._chunk_counter == 1 or self._chunk_counter % 50 == 0:
                self.logger.event(
                    "stream.tx",
                    bytes_in=int(telemetry.get("bytes_in", len(chunk))),
                    bytes_out=int(telemetry.get("bytes_out", 0)),
                    ch_in=int(telemetry.get("ch_in", 1)),
                    ch_out=int(telemetry.get("ch_out", 1)),
                    sr=int(telemetry.get("sr", self.stream_cfg.sample_rate)),
                    chunk_ms=int(telemetry.get("chunk_ms", self.stream_cfg.chunk_ms)),
                    ordinal=self._chunk_counter,
                )
        except Exception as e:
            self.logger.event("audio.append.error", error=str(e))
            raise

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
        modalities = getattr(prefs, "modalities", ["text", "audio"])
        voice = getattr(prefs, "voice", "verse") or "verse"
        instructions = getattr(prefs, "instructions", "")

        try:
            message = build_response_create(voice=voice, instructions=instructions, modalities=list(modalities))
            await self.transport.send(message)
            self.logger.event("response.create", voice=voice, modalities=",".join(modalities))
        except Exception as e:
            self.logger.event("response.create.error", error=str(e))
            raise

    def _start_audio_capture(self) -> None:
        """Start audio capture thread (generator → queue)."""
        if self._capture_thread and self._capture_thread.is_alive():
            return

        # policz bajty na chunk
        cap_cfg = self._capture_cfg_dict
        sr = int(self._capture_cfg.sample_rate)
        chunk_ms = int(self.stream_cfg.chunk_ms)
        chunk_size = int(self._capture_cfg.bytes_for_ms(chunk_ms))

        self.logger.event(
            "capture.start",
            sample_rate=sr,
            chunk_ms=chunk_ms,
            chunk_bytes=chunk_size,
            channels=int(self._capture_cfg.channels),
        )

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
        if self._audio_sender_task and not self._audio_sender_task.done():
            self._audio_sender_task.cancel()
            try:
                await self._audio_sender_task
            except asyncio.CancelledError:
                pass
            finally:
                self._audio_sender_task = None

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

    def _mask_endpoint(self, endpoint: str) -> str:
        if not endpoint:
            return ""
        return endpoint.replace("model=", "model=***")
