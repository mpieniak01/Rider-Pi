"""PTT (Push-to-Talk) state management for streaming voice service.

Extracted from svc_stream.py (Issue mpieniak01/Rider-Pi#58 - MOVE-FIRST refactoring).
Handles PTT keyboard control, state flags (~700ms silence, max_turn_ms from config),
and beep on PTT start. NO API CHANGES - methods signatures preserved.
"""

from __future__ import annotations

import asyncio
import sys
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class StreamingVoicePTTMixin:
    """PTT state management methods (extracted from StreamingVoiceService).

    This mixin provides PTT (Push-to-Talk) keyboard control and state flags
    that were in StreamingVoiceService, extracted via MOVE-FIRST approach.
    Expects parent class to have: logger, config, stop_event, ptt_enabled,
    ptt_active, _any_audio_since_commit, _publish_ui_state(), barge_in_event,
    _capture_thread, _audio_capture_thread(), _loop, connected,
    _commit_audio_buffer(), PlaybackConfig, play_ding().
    """

    def _ptt_keyboard_thread(self) -> None:
        """Toggle PTT on each ENTER press. Start → capture; Stop → commit."""
        self.logger.event("ptt.keyboard.start")  # type: ignore[attr-defined]
        while not self.stop_event.is_set():  # type: ignore[attr-defined]
            try:
                line = sys.stdin.readline()
                if line is None:
                    break
                # ENTER → toggle
                if not self.ptt_active:  # type: ignore[attr-defined]
                    # start PTT
                    self.ptt_active = True  # type: ignore[attr-defined]
                    self._any_audio_since_commit = False  # type: ignore[attr-defined]
                    self._publish_ui_state("hearing")  # type: ignore[attr-defined]
                    # barge-in: przerwij TTS
                    self.barge_in_event.set()  # type: ignore[attr-defined]

                    # Play beep if enabled
                    service_cfg = self.config.get("service", {})  # type: ignore[attr-defined]
                    if service_cfg.get("beep", False):
                        try:
                            from .playback import PlaybackConfig, play_ding

                            playback_cfg = PlaybackConfig(**self.config.get("playback", {}))  # type: ignore
                            play_ding(playback_cfg, self.logger)  # type: ignore[attr-defined]
                        except Exception as e:
                            self.logger.event("ptt.beep.error", error=str(e))  # type: ignore[attr-defined]

                    # Upewnij się, że capture żyje (WM8960/dsnoop potrafi się zamknąć)
                    # type: ignore[attr-defined]
                    if not (self._capture_thread and self._capture_thread.is_alive()):  # type: ignore
                        try:
                            th = threading.Thread(
                                target=self._audio_capture_thread,  # type: ignore[attr-defined]
                                name="voice-stream-capture",
                                daemon=True,
                            )
                            th.start()
                            self._capture_thread = th  # type: ignore[attr-defined]
                            self.logger.event("capture.restart.ptt")  # type: ignore[attr-defined]
                        except Exception as e:
                            self.logger.event("capture.restart.error", error=str(e))  # type: ignore[attr-defined]

                    self.logger.event("ptt.toggle", state="start")  # type: ignore[attr-defined]
                else:
                    # stop PTT
                    self.ptt_active = False  # type: ignore[attr-defined]
                    # type: ignore[attr-defined]
                    self.logger.event(
                        "ptt.toggle",
                        state="stop",
                        any_audio=self._any_audio_since_commit,  # type: ignore
                    )
                    # commit tylko jeśli coś powiedzieliśmy
                    # type: ignore[attr-defined]
                    if self._any_audio_since_commit and self._loop and self.connected:  # type: ignore
                        try:
                            # type: ignore[attr-defined]
                            fut = asyncio.run_coroutine_threadsafe(
                                self._commit_audio_buffer(),
                                self._loop,  # type: ignore[attr-defined]
                            )

                            def _done(f):
                                try:
                                    f.result()
                                except Exception as e:
                                    # type: ignore[attr-defined]
                                    self.logger.event("ptt.commit.future_error", error=str(e))  # type: ignore

                            fut.add_done_callback(_done)
                            self.logger.event("ptt.commit.dispatched")  # type: ignore[attr-defined]
                        except Exception as e:
                            self.logger.event("ptt.commit.error", error=str(e))  # type: ignore[attr-defined]
                    # UI „thinking" aż do response
                    self._publish_ui_state("thinking")  # type: ignore[attr-defined]
                    self._any_audio_since_commit = False  # type: ignore[attr-defined]
            except Exception as e:
                self.logger.event("ptt.keyboard.error", error=str(e))  # type: ignore[attr-defined]
                break
        self.logger.event("ptt.keyboard.exit")  # type: ignore[attr-defined]
