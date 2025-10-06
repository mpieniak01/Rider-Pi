# apps/voice/audio_tx.py
"""Audio transmission module for voice streaming.

Extracted from svc_stream.py (Issue mpieniak01/Rider-Pi#58 PR-2).
Handles audio capture thread, optional VAD, segmentation, and queue management.
"""

from __future__ import annotations

import queue
import threading
from typing import TYPE_CHECKING, Any, Callable

from .stream_chunks import calculate_chunk_size
from .svc_audio import capture_continuous

if TYPE_CHECKING:
    from . import voice_logging


class AudioTransmitter:
    """Manages audio capture and transmission to WebSocket queue."""

    def __init__(
        self,
        config: dict[str, Any],
        stream_cfg: Any,
        audio_queue: queue.Queue,
        logger: voice_logging.VoiceLogger,
        stop_event: threading.Event,
        ptt_enabled: bool = False,
    ):
        """Initialize audio transmitter.

        Args:
            config: Full service configuration dict
            stream_cfg: Stream configuration object
            audio_queue: Queue to push captured audio chunks
            logger: Voice logger instance
            stop_event: Threading event to signal shutdown
            ptt_enabled: Whether PTT mode is active
        """
        self.config = config
        self.stream_cfg = stream_cfg
        self.audio_queue = audio_queue
        self.logger = logger
        self.stop_event = stop_event
        self.ptt_enabled = ptt_enabled

        # State tracking
        self.ptt_active = False
        self._ptt_was_active = False
        self._any_audio_since_commit = False
        self.connected = False
        self.barge_in_event = threading.Event()
        self._audio_drops = 0

        # Callbacks (set by parent)
        self.on_ptt_commit: Callable[[], None] | None = None
        self.on_barge_in: Callable[[], None] | None = None

        # Thread handle
        self._capture_thread: threading.Thread | None = None

    def start_capture(self) -> None:
        """Start capture thread if not already running."""
        if self._capture_thread and self._capture_thread.is_alive():
            return

        def _target():
            try:
                self._audio_capture_thread()
            except Exception as e:
                self.logger.event("capture.thread.error", error=str(e))

        self._capture_thread = threading.Thread(
            target=_target,
            name="voice-stream-capture",
            daemon=True,
        )
        self._capture_thread.start()
        self.logger.event("capture.started")

    def stop_capture(self) -> None:
        """Stop capture thread."""
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
            self.logger.event("capture.stopped")

    def _audio_capture_thread(self) -> None:
        """Capture audio and feed to WebSocket queue."""
        try:
            capture_cfg = self.config.get("capture", {}) or {}
            sample_rate = int(capture_cfg.get("sample_rate", 16000))
            chunk_ms = int(self.stream_cfg.chunk_ms)
            chunk_size = calculate_chunk_size(sample_rate, chunk_ms)

            for audio_chunk in capture_continuous(capture_cfg, chunk_size):
                # Fallback commit on PTT STOP (edge True->False)
                try:
                    if (
                        self.ptt_enabled
                        and self._ptt_was_active
                        and (not self.ptt_active)
                        and self._any_audio_since_commit
                    ):
                        if self.on_ptt_commit:
                            self.on_ptt_commit()
                        self.logger.event("ptt.commit.fallback.dispatch")
                        self._any_audio_since_commit = False
                except Exception as _e:
                    self.logger.event("ptt.commit.fallback.guard_error", error=str(_e))

                # Update state for next iteration
                self._ptt_was_active = bool(self.ptt_active)

                if self.stop_event.is_set():
                    break

                # Handle barge-in event
                if self.barge_in_event.is_set():
                    if self.on_barge_in:
                        self.on_barge_in()
                    self.barge_in_event.clear()

                # GATE: send audio ONLY when PTT active or PTT disabled
                if audio_chunk and self.connected and (self.ptt_active or not self.ptt_enabled):
                    try:
                        self.audio_queue.put(audio_chunk, block=False)
                    except queue.Full:
                        # Queue full - drop oldest and add new (backpressure)
                        self._audio_drops += 1
                        if self._audio_drops % 10 == 1:  # Log every 10th drop
                            self.logger.event("audio_queue.full", drops=self._audio_drops)
                        try:
                            self.audio_queue.get_nowait()  # Remove oldest
                            self.audio_queue.put(audio_chunk, block=False)
                        except Exception as e:
                            self.logger.event("audio_queue.fallback_error", error=str(e))

        except Exception as e:
            self.logger.event("audio_capture_error", error=str(e))
        finally:
            # Put None only on global stop/reconnect
            if self.stop_event.is_set() or not self.connected:
                self.audio_queue.put(None)
