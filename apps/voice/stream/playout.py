# apps/voice/stream/playout.py
"""Audio capture and TTS playback worker threads for streaming voice service.

This module contains the worker thread management for:
- Audio capture (microphone → queue)
- TTS playback (queue → audio output)
"""

from __future__ import annotations

import contextlib
import queue
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..capture import CaptureConfig
    from ..playback import PlaybackConfig
    from ..voice_logging import VoiceLogger


class StreamPlayoutMixin:
    """Mixin providing audio capture and TTS playback workers for StreamingVoiceService."""

    # Required attributes (defined in main service class)
    logger: VoiceLogger
    config: dict[str, Any]
    stream_cfg: Any  # StreamConfig
    ptt_state: Any  # PTTStateMachine
    stop_event: Any  # threading.Event
    barge_in_event: Any  # threading.Event
    audio_queue: Any  # queue.Queue
    tts_player_queue: Any  # queue.Queue
    _capture_cfg: CaptureConfig
    _capture_cfg_dict: dict[str, Any]
    _playback_cfg: PlaybackConfig
    _capture_thread: threading.Thread | None
    _tts_player_thread: threading.Thread | None

    # ──────────────────────────────────────────────────────────────────────────
    # Audio capture worker

    def _start_audio_capture(self) -> None:
        """Start audio capture thread (generator → queue)."""
        from ..svc_audio import capture_continuous

        if self._capture_thread and self._capture_thread.is_alive():
            return

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
                try:
                    self.audio_queue.put_nowait(None)
                except Exception:
                    pass

        self._capture_thread = threading.Thread(target=capture_target, name="stream-capture", daemon=True)
        self._capture_thread.start()

    # ──────────────────────────────────────────────────────────────────────────
    # TTS playback worker

    def _start_tts_player(self) -> None:
        """Start TTS player thread."""
        if self._tts_player_thread and self._tts_player_thread.is_alive():
            return

        def player_target():
            # Używamy audio.playback.start_stream; PlaybackConfig mamy w self._playback_cfg
            from ..audio.playback import start_stream  # type: ignore
            from .state import PTTEvent

            stream = None
            try:
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
                            # Oczekujemy PCM16; session.update ustawia output_audio_format=pcm16/16k/mono.
                            stream = start_stream("pcm16", self._playback_cfg, self.logger)
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
