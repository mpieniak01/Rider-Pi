# apps/voice/audio_rx_tts.py
"""Audio reception and TTS playback module for voice streaming.

Extracted from svc_stream.py (Issue mpieniak01/Rider-Pi#58 PR-2).
Handles jitter buffer, barge-in pause/flush, and streaming TTS playback.
"""

from __future__ import annotations

import queue
import threading
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from . import voice_logging


class AudioReceiver:
    """Manages TTS audio reception and playback with jitter buffering."""

    def __init__(
        self,
        config: dict[str, Any],
        stream_cfg: Any,
        tts_queue: queue.Queue,
        logger: voice_logging.VoiceLogger,
        stop_event: threading.Event,
        barge_in_event: threading.Event,
    ):
        """Initialize audio receiver.

        Args:
            config: Full service configuration dict
            stream_cfg: Stream configuration object
            tts_queue: Queue containing TTS audio chunks to play
            logger: Voice logger instance
            stop_event: Threading event to signal shutdown
            barge_in_event: Event signaling barge-in (interrupt playback)
        """
        self.config = config
        self.stream_cfg = stream_cfg
        self.tts_queue = tts_queue
        self.logger = logger
        self.stop_event = stop_event
        self.barge_in_event = barge_in_event

        # Callbacks (set by parent)
        self.on_playback_start: Callable[[], None] | None = None
        self.on_playback_end: Callable[[], None] | None = None

        # Thread handle
        self._player_thread: threading.Thread | None = None

    def start_playback(self) -> None:
        """Start TTS playback thread if not already running."""
        if self._player_thread and self._player_thread.is_alive():
            return

        def _target():
            try:
                self._tts_player_loop()
            except Exception as e:
                self.logger.event("tts.player.thread.error", error=str(e))

        self._player_thread = threading.Thread(
            target=_target,
            name="voice-stream-tts-player",
            daemon=True,
        )
        self._player_thread.start()
        self.logger.event("tts.player.started")

    def stop_playback(self) -> None:
        """Stop TTS playback thread."""
        self.stop_event.set()
        try:
            if self._player_thread and self._player_thread.is_alive():
                self._player_thread.join(timeout=0.5)
        except Exception:
            pass
        finally:
            self._player_thread = None
            self.logger.event("tts.player.stopped")

    def _tts_player_loop(self) -> None:
        """Play TTS audio from queue (streaming, one process per response)."""
        from .playback import PlaybackConfig, play_bytes, start_stream

        try:
            playback_cfg = PlaybackConfig(**self.config.get("playback", {}))
            # Buffer for start (jitter buffer), before we start stream
            prebuffer = bytearray()
            threshold = max(1, self.stream_cfg.jitter_buffer_ms) * 32  # ~32B/ms @ 16kHz mono
            stream = None  # PlaybackStream or None

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
                    # Handle barge-in: immediately end current stream
                    if self.barge_in_event.is_set():
                        _close_stream()
                        prebuffer.clear()
                        self.barge_in_event.clear()

                    chunk = self.tts_queue.get(timeout=0.1)

                    if chunk is None:
                        # End of current TTS response
                        if stream is None:
                            if prebuffer:
                                try:
                                    play_bytes(bytes(prebuffer), "pcm16", playback_cfg)
                                except Exception as _e:
                                    self.logger.event("tts.play_once.error", error=str(_e))
                            prebuffer.clear()
                        _close_stream()
                        if self.on_playback_end:
                            self.on_playback_end()
                        continue

                    # We have data
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
                                if self.on_playback_start:
                                    self.on_playback_start()
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
