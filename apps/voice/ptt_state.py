# apps/voice/ptt_state.py
"""PTT (Push-to-Talk) state automation for voice streaming.

Extracted from svc_stream.py and state.py (Issue mpieniak01/Rider-Pi#58 PR-2).
Handles PTT debounce, commit timing, fire-and-forget vs wait-for-ack modes.
Integrates with apps/voice/stream/state.py PTTStateMachine for state tracking.
"""

from __future__ import annotations

import os
import select
import sys
import threading
import time
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from . import voice_logging


def _env_int(name: str, default: int) -> int:
    try:
        raw = os.environ.get(name, "")
        return int(raw.strip() or default)
    except Exception:
        return default


class _RateLimiter:
    """Simple rate limiter: allows log every N ms per key."""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}

    def allow(self, key: str, every_ms: int) -> bool:
        now = time.monotonic()
        last = self._last.get(key, 0.0)
        if (now - last) * 1000.0 >= max(1, every_ms):
            self._last[key] = now
            return True
        return False


class PTTController:
    """PTT controller with keyboard handling and auto-commit logic."""

    def __init__(
        self,
        logger: voice_logging.VoiceLogger,
        config: dict,
        stop_event: threading.Event,
    ):
        """Initialize PTT controller.

        Args:
            logger: Voice logger instance
            config: Service configuration dict
            stop_event: Threading event to signal shutdown
        """
        self.logger = logger
        self.config = config
        self.stop_event = stop_event

        # PTT state
        self.ptt_enabled = False
        self.ptt_active = False
        self._any_audio_since_commit = False
        self._ptt_was_active = False
        self._ptt_lock = threading.RLock()
        self._ptt_watchdog_running = False
        self._log_limiter = _RateLimiter()

        # Timing config
        self.last_audio_activity_ts: float = time.monotonic()

        # Callbacks (set by parent)
        self.on_commit: Callable[[], None] | None = None
        self.on_state_change: Callable[[str], None] | None = None
        self.on_barge_in: Callable[[], None] | None = None
        self.on_capture_restart: Callable[[], None] | None = None

        # Thread handles
        self._keyboard_thread: threading.Thread | None = None
        self._watchdog_thread: threading.Thread | None = None

    def _get_turn_cfg(self) -> tuple[int, int, int]:
        """Returns (max_turn_ms, silence_ms, tick_ms)."""
        svc = self.config.get("service", {})
        turn = svc.get("turn", {}) if isinstance(svc, dict) else {}
        max_turn_ms = int(turn.get("max_turn_ms", 15000))
        # Default silence 700 ms (can override with ENV)
        silence_ms = _env_int("VOICE_PTT_SILENCE_MS", int(turn.get("silence_ms", 700)))
        tick_ms = _env_int("VOICE_PTT_WATCHDOG_TICK_MS", 50)
        return max(1, max_turn_ms), max(0, silence_ms), max(10, tick_ms)

    def _purge_audio_queue(self) -> int:
        """Clear pending audio frames, return number of removed elements."""
        # This is called from parent's audio_queue
        # Placeholder - actual implementation depends on parent's queue
        return 0

    def schedule_commit(self) -> None:
        """Schedule commit with minimal waiting logic; non-blocking."""
        try:
            # 1) Immediately stop sending pending frames
            purged = self._purge_audio_queue()
            if purged and self._log_limiter.allow("ptt.queue.purged", _env_int("VOICE_PTT_ERROR_EVERY_MS", 1000)):
                self.logger.event("ptt.queue.purged", dropped=purged)

            # 2) Trigger commit callback
            if self.on_commit:
                self.on_commit()

            # 3) Log commit dispatched
            self.logger.event("ptt.commit.dispatched")

        except Exception as e:
            if self._log_limiter.allow("ptt.commit.error", _env_int("VOICE_PTT_ERROR_EVERY_MS", 1000)):
                self.logger.event("ptt.commit.error", error=str(e))

    def _ptt_watchdog_thread_impl(self) -> None:
        """Watch over turn length and silence. Stop PTT and commit."""
        try:
            max_turn_ms, silence_ms, tick_ms = self._get_turn_cfg()
            start_ts = time.monotonic()
            last_act = self.last_audio_activity_ts
            any_audio = self._any_audio_since_commit

            self.logger.event(
                "ptt.watchdog.start",
                max_turn_ms=max_turn_ms,
                silence_ms=silence_ms,
                tick_ms=tick_ms,
            )

            while not self.stop_event.is_set():
                # Safe read of shared fields
                with self._ptt_lock:
                    active = bool(self.ptt_active)
                    any_audio = bool(self._any_audio_since_commit)
                    last_act = float(self.last_audio_activity_ts)

                if not active:
                    break

                now = time.monotonic()
                elapsed_ms = int((now - start_ts) * 1000.0)
                silence_elapsed_ms = int((now - last_act) * 1000.0)

                # Condition 1: max turn length
                if elapsed_ms >= max_turn_ms:
                    if self._log_limiter.allow("ptt.watchdog.max_turn", 500):
                        self.logger.event("ptt.watchdog.max_turn", elapsed_ms=elapsed_ms)
                    with self._ptt_lock:
                        self.ptt_active = False
                    # Commit only if we said something
                    if any_audio:
                        self.schedule_commit()
                        if self.on_state_change:
                            self.on_state_change("thinking")
                        self._any_audio_since_commit = False
                    break

                # Condition 2: silence after activity
                if silence_ms > 0 and any_audio and silence_elapsed_ms >= silence_ms:
                    if self._log_limiter.allow("ptt.watchdog.silence", 500):
                        self.logger.event(
                            "ptt.watchdog.silence",
                            silence_elapsed_ms=silence_elapsed_ms,
                        )
                    with self._ptt_lock:
                        self.ptt_active = False
                    self.schedule_commit()
                    if self.on_state_change:
                        self.on_state_change("thinking")
                    self._any_audio_since_commit = False
                    break

                time.sleep(tick_ms / 1000.0)

        except Exception as e:
            if self._log_limiter.allow("ptt.watchdog.error", _env_int("VOICE_PTT_ERROR_EVERY_MS", 1000)):
                self.logger.event("ptt.watchdog.error", error=str(e))
        finally:
            self._ptt_watchdog_running = False
            try:
                self.logger.event("ptt.watchdog.exit")
            except Exception:
                pass

    def _ptt_keyboard_thread_impl(self) -> None:
        """Toggle PTT on each ENTER press. Start → capture; Stop → commit."""
        self.logger.event("ptt.keyboard.start")
        try:
            # Don't block on stdin.readline(); poll with short timeout
            while not self.stop_event.is_set():
                try:
                    # select on stdin; timeout 100 ms to react to stop_event
                    rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
                    if not rlist:
                        continue

                    line = sys.stdin.readline()
                    if line is None:
                        break
                    if line == "":
                        # EOF/tty closed
                        break

                    # Accept only "bare ENTER"
                    if line.strip() != "":
                        continue

                    with self._ptt_lock:
                        active = bool(self.ptt_active)

                    if not active:
                        # ---- START PTT ----
                        with self._ptt_lock:
                            self.ptt_active = True
                            self._any_audio_since_commit = False
                            # Reset activity timer - start now
                            self.last_audio_activity_ts = time.monotonic()

                        if self.on_state_change:
                            self.on_state_change("hearing")

                        # Barge-in: interrupt TTS immediately
                        if self.on_barge_in:
                            self.on_barge_in()

                        # Beep (optionally, non-blocking)
                        try:
                            service_cfg = self.config.get("service", {})
                            if service_cfg.get("beep", False):

                                def _do_beep():
                                    try:
                                        from .playback import PlaybackConfig, play_ding

                                        playback_cfg = PlaybackConfig(**self.config.get("playback", {}))
                                        play_ding(playback_cfg, self.logger)
                                    except Exception as _e:
                                        if self._log_limiter.allow(
                                            "ptt.beep.error", _env_int("VOICE_PTT_ERROR_EVERY_MS", 1000)
                                        ):
                                            self.logger.event("ptt.beep.error", error=str(_e))

                                threading.Thread(target=_do_beep, name="voice-ptt-beep", daemon=True).start()
                        except Exception as e:
                            if self._log_limiter.allow("ptt.beep.error", _env_int("VOICE_PTT_ERROR_EVERY_MS", 1000)):
                                self.logger.event("ptt.beep.error", error=str(e))

                        # Ensure capture is alive
                        if self.on_capture_restart:
                            self.on_capture_restart()

                        # Start watchdog for turn (after PTT start)
                        if not self._ptt_watchdog_running:
                            self._ptt_watchdog_running = True
                            threading.Thread(
                                target=self._ptt_watchdog_thread_impl,
                                name="voice-ptt-watchdog",
                                daemon=True,
                            ).start()

                        self.logger.event("ptt.toggle", state="start")

                    else:
                        # ---- STOP PTT (manual) ----
                        with self._ptt_lock:
                            self.ptt_active = False
                            any_audio = bool(self._any_audio_since_commit)

                        # Event STOP + whether there was speech
                        self.logger.event(
                            "ptt.toggle",
                            state="stop",
                            any_audio=any_audio,
                        )

                        # If there was speech and we're connected → COMMIT
                        if any_audio:
                            self.schedule_commit()

                        # UI "thinking" until response.* (listen via stream)
                        if self.on_state_change:
                            self.on_state_change("thinking")
                        with self._ptt_lock:
                            self._any_audio_since_commit = False

                except Exception as e:
                    # PTT loop error - single line, rate-limited (no flood)
                    if self._log_limiter.allow("ptt.keyboard.error", _env_int("VOICE_PTT_ERROR_EVERY_MS", 1000)):
                        self.logger.event("ptt.keyboard.error", error=str(e))
                    continue
        finally:
            self.logger.event("ptt.keyboard.exit")

    def start_keyboard_thread(self) -> None:
        """Start PTT keyboard thread."""
        if self._keyboard_thread and self._keyboard_thread.is_alive():
            return

        self._keyboard_thread = threading.Thread(
            target=self._ptt_keyboard_thread_impl,
            name="voice-ptt-keyboard",
            daemon=True,
        )
        self._keyboard_thread.start()
        self.logger.event("ptt.keyboard.thread_started")

    def stop_keyboard_thread(self) -> None:
        """Stop PTT keyboard thread."""
        self.stop_event.set()
        try:
            if self._keyboard_thread and self._keyboard_thread.is_alive():
                self._keyboard_thread.join(timeout=0.5)
        except Exception:
            pass
        finally:
            self._keyboard_thread = None
            self.logger.event("ptt.keyboard.thread_stopped")
