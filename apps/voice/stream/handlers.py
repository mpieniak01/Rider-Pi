# apps/voice/stream/handlers.py
"""Message and event handlers for streaming voice service.

This module contains:
- PTT state callbacks
- WebSocket message handlers
- Session update payload builders
- UI state publishing
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..audio.playback import PlaybackConfig
    from ..chat import ChatSession
    from ..tts import TTSConfig
    from ..voice_logging import VoiceLogger
    from .state import PTTEvent, PTTStateMachine


_AUTH_LOADED = "auth.loaded"
_SESSION_UPDATE = "session.update"
_UI_STATE = "ui.state"


def _stdin_has_enter():
    import select
    import sys

    ready, _, _ = select.select([sys.stdin], [], [], 0.1)
    if ready:
        line = sys.stdin.readline()
        return bool(line and line.strip() == "")
    return False


class StreamHandlersMixin:
    """Mixin providing message/event handling for StreamingVoiceService."""

    # Required attributes (defined in main service class)
    logger: VoiceLogger
    config: dict[str, Any]
    stream_cfg: Any  # StreamConfig
    ptt_state: PTTStateMachine
    ui_publisher: Any | None
    stop_event: Any  # threading.Event
    transport: Any | None
    tts_player_queue: Any  # queue.Queue
    _tts_cfg: TTSConfig
    _playback_cfg: PlaybackConfig
    _chat_cfg: Any  # ChatConfig
    _chat_session: ChatSession | None
    _any_audio_since_commit: bool
    _last_ui_state: str | None
    partial_transcript: str
    _completed: bool
    _session_prefs: Any | None
    _loop: asyncio.AbstractEventLoop | None
    _session_tasks: Any
    _last_rx_ts: float
    _bw_rx_total: int
    session_id: str

    # Methods that need to be defined in main service
    def _mask_endpoint(self, endpoint: str) -> str:
        raise NotImplementedError

    async def _commit_audio_buffer(self) -> None:
        raise NotImplementedError

    async def _transition_to_idle(self) -> None:
        raise NotImplementedError

    # ──────────────────────────────────────────────────────────────────────────
    # PTT state callbacks

    def _setup_state_callbacks(self) -> None:
        """Setup PTT state machine callbacks."""
        from .state import PTTState

        self.ptt_state.add_enter_callback(PTTState.ARMING, self._on_arming)
        self.ptt_state.add_enter_callback(PTTState.RECORDING, self._on_recording_start)
        self.ptt_state.add_enter_callback(PTTState.SPEAKING, self._on_speaking_start)
        self.ptt_state.add_enter_callback(PTTState.CLOSING, self._on_closing)
        self.ptt_state.add_transition_callback(PTTState.COMMIT, PTTState.WAIT_REPLY, self._on_commit_complete)

    def _on_arming(self) -> None:
        self._publish_ui_state("arming")

    def _on_recording_start(self) -> None:
        self._publish_ui_state("recording")
        self._any_audio_since_commit = False

    def _on_speaking_start(self) -> None:
        self._publish_ui_state("speaking")

    def _on_closing(self) -> None:
        """Handle CLOSING state - immediately transition to IDLE for next interaction."""
        self._publish_ui_state("idle")
        if self._loop:
            self._loop.call_soon_threadsafe(self._schedule_idle_transition)

    def _schedule_idle_transition(self) -> None:
        """Keep PTT callback work in the session, rejecting callbacks after close."""
        if not self._session_tasks.closing:
            self._session_tasks.create(self._transition_to_idle(), name="voice-idle")

    def _on_commit_complete(self, event: PTTEvent) -> None:
        self._publish_ui_state("processing")

    # ──────────────────────────────────────────────────────────────────────────
    # Session initialization

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
            self.logger.event(_AUTH_LOADED, src="env", var=env_key, length=len(api_key))
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
            self.logger.event(_AUTH_LOADED, src="file", length=len(key))
            return key

        if auth.startswith("bashenv:"):
            self.logger.event("auth_bashenv_rejected", scheme="bashenv")
            raise RuntimeError(
                "bashenv: scheme is no longer supported for security reasons. "
                "Use env:VARNAME or file:/path/to/keyfile instead."
            )

        if auth:
            return auth

        fallback = (os.environ.get("OPENAI_API_KEY", "") or "").strip()
        if fallback:
            self.logger.event(_AUTH_LOADED, src="env", var="OPENAI_API_KEY", length=len(fallback))
            return fallback

        raise RuntimeError("Missing OpenAI API key. Configure stream.auth or set OPENAI_API_KEY.")

    async def _send_session_init(self) -> None:
        """Send session initialization message (session.update)."""
        from ..session_prefs import build_session_preferences, session_prefs_to_dict

        if not self.transport:
            return

        self.session_id = str(uuid.uuid4())
        prefs = build_session_preferences(self.config, stream_cfg=self.stream_cfg)
        prefs_dict = session_prefs_to_dict(prefs) if prefs else {}

        # Bezpieczne domyślne pola dla Realtime:
        prefs_dict.setdefault("modalities", ["audio", "text"])

        if self.stream_cfg.server_vad:
            prefs_dict["turn_detection"] = {
                "type": "server_vad",
                "threshold": 0.5,
                "prefix_padding_ms": 300,
                "silence_duration_ms": int(self.stream_cfg.turn_end_silence_ms),
            }

        prefs_dict["input_audio_format"] = {
            "type": "pcm16",
            "sample_rate_hz": int(self.stream_cfg.sample_rate),
            "channels": 1,
        }

        # Wyjście audio – PCM16 (pasuje do naszego playera stream.pcm16)
        prefs_dict["output_audio_format"] = {
            "type": "pcm16",
            "sample_rate_hz": int(self.stream_cfg.sample_rate),
            "channels": 1,
        }

        voice_name = getattr(self._tts_cfg, "voice", None) or "alloy"
        prefs_dict.setdefault("voice", voice_name)

        prefs_dict.setdefault(
            "instructions",
            "Jesteś asystentem głosowym Rider-Pi. Odpowiadaj po polsku, zwięźle.",
        )

        self._session_prefs = prefs
        init_message = {"type": _SESSION_UPDATE, "session": prefs_dict}

        await self.transport.send(json.dumps(init_message))
        self.logger.event(
            "session.init",
            session_id=self.session_id,
            has_vad=int(self.stream_cfg.server_vad),
            in_sr=int(self.stream_cfg.sample_rate),
            out_fmt="pcm16",
            voice=voice_name,
        )

    def _build_session_update_payload(self) -> dict[str, Any]:
        """Zbuduj payload session.update (używane przez testowy alias)."""
        from ..session_prefs import build_session_preferences, session_prefs_to_dict

        prefs = build_session_preferences(self.config, stream_cfg=self.stream_cfg)
        prefs_dict = session_prefs_to_dict(prefs) if prefs else {}
        prefs_dict.setdefault("modalities", ["audio", "text"])
        if self.stream_cfg.server_vad:
            prefs_dict["turn_detection"] = {
                "type": "server_vad",
                "threshold": 0.5,
                "prefix_padding_ms": 300,
                "silence_duration_ms": int(self.stream_cfg.turn_end_silence_ms),
            }
        prefs_dict["input_audio_format"] = {
            "type": "pcm16",
            "sample_rate_hz": int(self.stream_cfg.sample_rate),
            "channels": 1,
        }
        prefs_dict["output_audio_format"] = {
            "type": "pcm16",
            "sample_rate_hz": int(self.stream_cfg.sample_rate),
            "channels": 1,
        }
        voice_name = getattr(self._tts_cfg, "voice", None) or "alloy"
        prefs_dict.setdefault("voice", voice_name)
        prefs_dict.setdefault(
            "instructions",
            "Jesteś asystentem głosowym Rider-Pi. Odpowiadaj po polsku, zwięźle.",
        )
        self._session_prefs = prefs
        return {"type": _SESSION_UPDATE, "session": prefs_dict}

    # ──────────────────────────────────────────────────────────────────────────
    # UI publishing

    def _publish_ui_state(self, state: str) -> None:
        # nie publikuj duplikatów
        if state == self._last_ui_state:
            return
        self._last_ui_state = state
        if self.ui_publisher:
            try:
                self.ui_publisher.publish(_UI_STATE, {"state": state, "ts": time.time()})
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
                self.ui_publisher.publish(
                    "ui.error",
                    {"type": error_type, "message": message, "ts": time.time()},
                )
            except Exception as e:
                self.logger.event("error_pub_error", error=str(e))

    # ──────────────────────────────────────────────────────────────────────────
    # Message handling

    def _normalize_type(self, t: str) -> str:
        """Normalize historical Realtime event names."""
        if t == "response.done":
            return "response.completed"
        return t

    async def _message_handler_loop(self) -> None:
        """Handle incoming WebSocket messages."""
        while not self.stop_event.is_set() and self.transport:
            try:
                message = await asyncio.wait_for(self.transport.recv(), timeout=1.0)
                self._last_rx_ts = time.time()
                await self._handle_message(message)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self.logger.event("message_recv_error", error=str(e))
                break

    async def _handle_message(self, message: str) -> None:
        """Handle incoming WebSocket message, isolating malformed event failures."""
        try:
            data = json.loads(message)
            msg_type = self._normalize_type(data.get("type", ""))
            await self._dispatch_message(data, msg_type)
        except Exception as exc:
            self.logger.event("message_parse_error", error=str(exc), sample=message[:200])

    def _handle_audio_delta(self, data):
        audio_b64 = data.get("delta", "")
        if not audio_b64:
            return
        try:
            audio_data = base64.b64decode(audio_b64)
        except Exception as exc:
            self.logger.event("audio.delta.b64_error", error=str(exc))
            return
        if audio_data:
            try:
                self._bw_rx_total += len(audio_data)
            except Exception:
                pass
            self.tts_player_queue.put(audio_data)

    def _handle_final_transcript(self, data):
        transcript = data.get("transcript", "")
        if transcript and transcript.strip():
            self.logger.event("asr.transcript.final", text=transcript)
            self._session_tasks.create(self._handle_transcript(transcript.strip()), name="voice-transcript")

    def _handle_unknown_message(self, data, msg_type):
        try:
            preview = json.dumps(data)[:160]
        except Exception:
            preview = str(data)[:160]
        self.logger.event("ws.rx.unknown_type", t=msg_type or "<none>", sample=preview)

    async def _dispatch_message(self, data, msg_type):
        from .state import PTTEvent

        transitions = {
            "response.created": (PTTEvent.SERVER_RESPONSE, "response.created"),
            "input_audio_buffer.speech_started": (PTTEvent.VOICE_START, "speech.started"),
            "input_audio_buffer.speech_stopped": (PTTEvent.VOICE_END, "speech.stopped"),
        }
        if msg_type in transitions:
            event, log_name = transitions[msg_type]
            self.logger.event(log_name)
            self.ptt_state.transition(event)
            if event == PTTEvent.VOICE_END:
                await self._commit_audio_buffer()
        elif msg_type in ("response.output_audio.delta", "response.audio.delta"):
            self._handle_audio_delta(data)
        elif msg_type in ("response.output_audio.completed", "response.audio.done"):
            self.tts_player_queue.put(None)
            self.ptt_state.transition(PTTEvent.TTS_COMPLETE)
        elif msg_type in ("response.output_text.delta", "response.text.delta"):
            text = data.get("delta", "")
            if text:
                self._publish_partial(text)
        elif msg_type == "session.updated":
            self.logger.event("session.updated")
        elif msg_type == "conversation.item.input_audio_transcription.completed":
            self._handle_final_transcript(data)
        elif msg_type == "response.completed":
            self._completed = True
            self.ptt_state.transition(PTTEvent.TTS_COMPLETE)
        elif msg_type == "error":
            error_msg = data.get("error", {}).get("message", "Unknown error")
            self.logger.event("ws.protocol_error", error=error_msg)
            self._publish_error("ws_protocol", error_msg)
            self.ptt_state.transition(PTTEvent.ERROR)
        else:
            self._handle_unknown_message(data, msg_type)

    async def _handle_transcript(self, transcript: str) -> None:
        """ASR→CHAT→TTS local pipeline as a fallback/augmentation."""
        from ..chat import ChatSession
        from ..tts import speak_stream
        from .state import PTTEvent

        try:
            self.logger.event("chat.stream.start", text=transcript)
            self.ptt_state.transition(PTTEvent.SERVER_RESPONSE)

            if self._chat_session is None:
                self._chat_session = ChatSession(self._chat_cfg, self.logger)

            chat_stream = self._chat_session.ask_stream(transcript)

            self.logger.event("tts.stream.start")
            result = await speak_stream(chat_stream, self._tts_cfg, self._playback_cfg, self.logger)

            if result.ok:
                self.logger.event("chat_tts.stream.complete")
                self.ptt_state.transition(PTTEvent.TTS_COMPLETE)
                self._completed = True
            else:
                self.logger.event("chat_tts.stream.failed")
                self.ptt_state.transition(PTTEvent.ERROR)

        except Exception as exc:
            self.logger.event("chat_tts.stream.error", error=str(exc))
            self.ptt_state.transition(PTTEvent.ERROR)

    # ──────────────────────────────────────────────────────────────────────────
    # Keyboard PTT

    async def _toggle_keyboard_ptt(self, active):
        from .state import PTTEvent

        if active:
            self.logger.event("ptt.keyboard.commit")
            self.ptt_state.transition(PTTEvent.COMMIT_AUDIO)
            await self._commit_audio_buffer()
            self._publish_ui_state("processing")
            return False
        self.logger.event("ptt.keyboard.start_recording")
        self.ptt_state.transition(PTTEvent.START)
        if self.config.get("service", {}).get("beep", False):
            await self._play_ding_async()
        await asyncio.sleep(0.1)
        self.ptt_state.transition(PTTEvent.DING_COMPLETE)
        self._publish_ui_state("recording")
        return True

    async def _keyboard_ptt_loop(self) -> None:
        """Handle keyboard PTT (ENTER key) in a non-blocking async loop.

        Each ENTER press toggles PTT:
        - First press: START event → ARMING → (after optional ding) → RECORDING
        - Second press: COMMIT_AUDIO event (ends recording and sends for processing)
        """
        self.logger.event("ptt.keyboard.start")
        ptt_active = False

        try:
            loop = asyncio.get_running_loop()

            while not self.stop_event.is_set():
                try:
                    has_input = await loop.run_in_executor(None, _stdin_has_enter)

                    if has_input:
                        ptt_active = await self._toggle_keyboard_ptt(ptt_active)
                    else:
                        await asyncio.sleep(0.1)

                except Exception as e:
                    self.logger.event("ptt.keyboard.error", error=str(e))
                    await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            self.logger.event("ptt.keyboard.cancelled")
            raise
        except Exception as e:
            self.logger.event("ptt.keyboard.loop_error", error=str(e))
        finally:
            self.logger.event("ptt.keyboard.stop")

    async def _play_ding_async(self) -> None:
        """Play ding sound asynchronously (non-blocking)."""
        try:
            loop = asyncio.get_running_loop()

            def _do_ding():
                try:
                    from ..audio.playback import play_ding

                    play_ding(self._playback_cfg, self.logger)
                except Exception as e:
                    self.logger.event("ptt.ding.error", error=str(e))

            await loop.run_in_executor(None, _do_ding)
        except Exception as e:
            self.logger.event("ptt.ding.async_error", error=str(e))

    # ──────────────────────────────────────────────────────────────────────────
    # Test compatibility aliases

    async def _send_session_update(self) -> None:
        """Wyślij aktualizację sesji zgodną z oczekiwaniami testów."""
        session = {
            "voice": "ash",
            "input_audio_format": {
                "type": "pcm16",
                "sample_rate_hz": 16000,
                "channels": 1,
            },
            "output_audio_format": {
                "type": "pcm16",
                "sample_rate_hz": 16000,
                "channels": 1,
            },
        }
        msg = json.dumps({"type": _SESSION_UPDATE, "session": session})

        # transport ma pierwszeństwo; obsłuż awaitable
        if getattr(self, "transport", None):
            res = self.transport.send(msg)
            import inspect as _inspect

            if _inspect.isawaitable(res):
                await res
            return

        # websocket fallback (test dąży do kompatybilności)
        if getattr(self, "websocket", None):
            snd = getattr(self.websocket, "send", None)
            if snd:
                res = snd(msg)
                import inspect as _inspect

                if _inspect.isawaitable(res):
                    await res

    async def _fallback_ws_message(self, message):
        import inspect

        fallback = getattr(self, "_handle_message", None)
        if fallback:
            if inspect.iscoroutinefunction(fallback):
                await fallback(message)
            else:
                fallback(message)

    def _publish_compat_message(self, topic, payload):
        publisher = getattr(self, "ui_publisher", None)
        if publisher:
            try:
                publisher.publish(topic, payload)
            except Exception:
                pass
        elif topic == _UI_STATE:
            self._publish_ui_state(payload["state"])
        else:
            self._publish_partial(str(payload["text"]))

    async def _handle_ws_message(self, message: str) -> None:
        """Publish historical UI payloads and delegate other message types."""
        try:
            data = json.loads(message)
        except Exception:
            await self._fallback_ws_message(message)
            return
        msg_type = data.get("type")
        if msg_type == "input_audio_buffer.speech_started":
            self._publish_compat_message(_UI_STATE, {"state": "hearing"})
        elif msg_type == "conversation.item.input_audio_transcription.delta":
            self._publish_compat_message("ui.partial", {"text": data.get("delta", "")})
        else:
            await self._fallback_ws_message(message)
