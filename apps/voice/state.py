# apps/voice/state.py
"""
PTT (Push-to-Talk) state management for streaming voice service.

Extracted from svc_stream.py (Issue mpieniak01/Rider-Pi#58 - MOVE-FIRST refactoring).
Handles PTT keyboard control, state flags (~700ms silence, max_turn_ms from config),
and beep on PTT start. NO API CHANGES - methods signatures preserved.
"""

from __future__ import annotations

import asyncio
import os
import select
import sys
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


def _env_int(name: str, default: int) -> int:
    try:
        raw = os.environ.get(name, "")
        return int(raw.strip() or default)
    except Exception:
        return default


class _RateLimiter:
    """Prosty limiter: pozwala na log co N ms na klucz."""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}

    def allow(self, key: str, every_ms: int) -> bool:
        now = time.monotonic()
        last = self._last.get(key, 0.0)
        if (now - last) * 1000.0 >= max(1, every_ms):
            self._last[key] = now
            return True
        return False


class StreamingVoicePTTMixin:
    """PTT state management methods (extracted from StreamingVoiceService).

    Expects parent class to have: logger, config, stop_event, ptt_enabled,
    ptt_active, _any_audio_since_commit, _publish_ui_state(), barge_in_event,
    _capture_thread, _audio_capture_thread(), _loop, connected,
    _commit_audio_buffer(), audio_queue, PlaybackConfig, play_ding().

    Dodatkowo (opcjonalnie):
    - last_audio_activity_ts: float (monotonic) – uaktualniane przez capture.
    """

    _log_limiter = _RateLimiter()

    # --- util: bezpieczne natychmiastowe czyszczenie kolejki audio ---
    def _purge_audio_queue(self) -> int:
        """Wyczyść zaległe ramki audio, zwróć liczbę usuniętych elementów."""
        try:
            q = getattr(self, "audio_queue", None)  # type: ignore[attr-defined]
            if q is None or not hasattr(q, "mutex"):
                return 0
            with q.mutex:  # type: ignore[attr-defined]
                n = len(q.queue)  # type: ignore[attr-defined]
                q.queue.clear()  # type: ignore[attr-defined]
                return n
        except Exception:
            return 0

    # --- wewnętrzne: odczyt ustawień czasu ---
    def _get_turn_cfg(self) -> tuple[int, int, int]:
        """Zwraca (max_turn_ms, silence_ms, tick_ms)."""
        svc = getattr(self, "config", {}).get("service", {})  # type: ignore[attr-defined]
        turn = svc.get("turn", {}) if isinstance(svc, dict) else {}
        max_turn_ms = int(turn.get("max_turn_ms", 15000))
        # domyślna cisza 700 ms (możesz nadpisać ENV-em)
        silence_ms = _env_int("VOICE_PTT_SILENCE_MS", int(turn.get("silence_ms", 700)))
        tick_ms = _env_int("VOICE_PTT_WATCHDOG_TICK_MS", 50)
        return max(1, max_turn_ms), max(0, silence_ms), max(10, tick_ms)

    # --- wspólna ścieżka commitowania po PTT STOP/auto-stop ---
    def _schedule_commit(self) -> None:
        """Zaplanuj commit + minimum logiki oczekiwania; bez blokowania wątku."""
        try:
            # 1) natychmiast przestań wysyłać zaległe ramki
            purged = self._purge_audio_queue()
            if purged and self._log_limiter.allow("ptt.queue.purged", _env_int("VOICE_PTT_ERROR_EVERY_MS", 1000)):
                self.logger.event("ptt.queue.purged", dropped=purged)  # type: ignore[attr-defined]

            # 2) zleć commit w pętli asyncio
            fut = asyncio.run_coroutine_threadsafe(
                self._commit_audio_buffer(),  # type: ignore[attr-defined]
                self._loop,  # type: ignore[attr-defined]
            )

            def _commit_done(f: asyncio.Future):
                try:
                    err = f.exception()
                    if err:
                        self.logger.event(  # type: ignore[attr-defined]
                            "ptt.commit.done",
                            ok=False,
                            error=f"{type(err).__name__}: {err}",
                        )
                    else:
                        self.logger.event("ptt.commit.done", ok=True)  # type: ignore[attr-defined]
                except Exception as _e:
                    if self._log_limiter.allow("ptt.commit.done.cb.error", _env_int("VOICE_PTT_ERROR_EVERY_MS", 1000)):
                        self.logger.event(  # type: ignore[attr-defined]
                            "ptt.commit.done.cb.error",
                            error=str(_e),
                        )

            fut.add_done_callback(_commit_done)

            # 3) krótkie czekanie probiercze (nie blokuje długo)
            wait_ms = _env_int("VOICE_PTT_COMMIT_WAIT_MS", 50)
            legacy_ms = _env_int("VOICE_PTT_COMMIT_TIMEOUT_MS", -1)
            if legacy_ms >= 0 and self._log_limiter.allow(
                "ptt.commit.legacy_timeout.warn", _env_int("VOICE_PTT_ERROR_EVERY_MS", 2000)
            ):
                self.logger.event(  # type: ignore[attr-defined]
                    "ptt.commit.legacy_timeout.warn",
                    note="VOICE_PTT_COMMIT_TIMEOUT_MS is deprecated; use VOICE_PTT_COMMIT_WAIT_MS",
                    legacy_ms=legacy_ms,
                )
                wait_ms = legacy_ms

            if wait_ms > 0 and self._log_limiter.allow(
                "ptt.commit.wait.start", _env_int("VOICE_PTT_ERROR_EVERY_MS", 250)
            ):
                self.logger.event("ptt.commit.wait.start")  # type: ignore[attr-defined]

            if wait_ms > 0:
                try:
                    fut.result(timeout=max(0.01, wait_ms / 1000.0))
                    if self._log_limiter.allow("ptt.commit.ok", _env_int("VOICE_PTT_ERROR_EVERY_MS", 250)):
                        self.logger.event("ptt.commit.ok")  # type: ignore[attr-defined]
                except Exception as e:
                    if self._log_limiter.allow("ptt.commit.future_error", _env_int("VOICE_PTT_ERROR_EVERY_MS", 1000)):
                        self.logger.event(  # type: ignore[attr-defined]
                            "ptt.commit.future_error",
                            error=f"{type(e).__name__}: {str(e) or '<no-message>'}",
                        )
                    self.logger.event("ptt.commit.dispatched")  # type: ignore[attr-defined]
                finally:
                    if self._log_limiter.allow("ptt.commit.wait.end", _env_int("VOICE_PTT_ERROR_EVERY_MS", 250)):
                        self.logger.event("ptt.commit.wait.end")  # type: ignore[attr-defined]
            else:
                self.logger.event("ptt.commit.dispatched")  # type: ignore[attr-defined]

        except Exception as e:
            if self._log_limiter.allow("ptt.commit.error", _env_int("VOICE_PTT_ERROR_EVERY_MS", 1000)):
                self.logger.event("ptt.commit.error", error=str(e))  # type: ignore[attr-defined]

    # --- watchdog PTT: auto-stop po ciszy lub po max_turn_ms ---
    def _ptt_watchdog_thread(self) -> None:
        """Czuwa nad długością tury i ciszą. Gasi PTT i robi commit."""
        try:
            max_turn_ms, silence_ms, tick_ms = self._get_turn_cfg()
            start_ts = time.monotonic()
            # jeżeli capture nie aktualizuje last_audio_activity_ts, wyłączy się tylko max_turn
            last_act = getattr(self, "last_audio_activity_ts", start_ts)
            any_audio = getattr(self, "_any_audio_since_commit", False)  # type: ignore[attr-defined]

            self.logger.event(  # type: ignore[attr-defined]
                "ptt.watchdog.start",
                max_turn_ms=max_turn_ms,
                silence_ms=silence_ms,
                tick_ms=tick_ms,
            )

            while not self.stop_event.is_set():  # type: ignore[attr-defined]
                # bezpieczny odczyt pól współdzielonych
                with self._ptt_lock:  # type: ignore[attr-defined]
                    active = bool(getattr(self, "ptt_active", False))  # type: ignore[attr-defined]
                    any_audio = bool(getattr(self, "_any_audio_since_commit", False))  # type: ignore[attr-defined]
                    last_act = float(getattr(self, "last_audio_activity_ts", last_act))

                if not active:
                    break

                now = time.monotonic()
                elapsed_ms = int((now - start_ts) * 1000.0)
                silence_elapsed_ms = int((now - last_act) * 1000.0)

                # warunek 1: max długość tury
                if elapsed_ms >= max_turn_ms:
                    if self._log_limiter.allow("ptt.watchdog.max_turn", 500):
                        self.logger.event("ptt.watchdog.max_turn", elapsed_ms=elapsed_ms)  # type: ignore[attr-defined]
                    with self._ptt_lock:  # type: ignore[attr-defined]
                        self.ptt_active = False  # type: ignore[attr-defined]
                    # commit tylko gdy coś powiedzieliśmy
                    if any_audio and getattr(self, "connected", False):  # type: ignore[attr-defined]
                        self._schedule_commit()
                        self._publish_ui_state("thinking")  # type: ignore[attr-defined]
                        self._any_audio_since_commit = False  # type: ignore[attr-defined]
                    break

                # warunek 2: cisza po aktywności
                if silence_ms > 0 and any_audio and silence_elapsed_ms >= silence_ms:
                    if self._log_limiter.allow("ptt.watchdog.silence", 500):
                        self.logger.event(  # type: ignore[attr-defined]
                            "ptt.watchdog.silence",
                            silence_elapsed_ms=silence_elapsed_ms,
                        )
                    with self._ptt_lock:  # type: ignore[attr-defined]
                        self.ptt_active = False  # type: ignore[attr-defined]
                    if getattr(self, "connected", False):  # type: ignore[attr-defined]
                        self._schedule_commit()
                        self._publish_ui_state("thinking")  # type: ignore[attr-defined]
                        self._any_audio_since_commit = False  # type: ignore[attr-defined]
                    break

                time.sleep(tick_ms / 1000.0)

        except Exception as e:
            if self._log_limiter.allow("ptt.watchdog.error", _env_int("VOICE_PTT_ERROR_EVERY_MS", 1000)):
                self.logger.event("ptt.watchdog.error", error=str(e))  # type: ignore[attr-defined]
        finally:
            self._ptt_watchdog_running = False  # type: ignore[attr-defined]
            try:
                self.logger.event("ptt.watchdog.exit")  # type: ignore[attr-defined]
            except Exception:
                pass

    def _ensure_ptt_lock(self) -> None:
        if not hasattr(self, "_ptt_lock"):
            self._ptt_lock = threading.RLock()  # type: ignore[attr-defined]

    def _ptt_keyboard_thread(self) -> None:
        """Toggle PTT on each ENTER press. Start → capture; Stop → commit."""
        self._ensure_ptt_lock()
        self.logger.event("ptt.keyboard.start")  # type: ignore[attr-defined]
        try:
            # Nie blokujemy się na stdin.readline(); pollujemy z krótkim timeoutem
            while not self.stop_event.is_set():  # type: ignore[attr-defined]
                try:
                    # select na stdin; timeout 100 ms, żeby reagować na stop_event
                    rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
                    if not rlist:
                        continue

                    line = sys.stdin.readline()
                    if line is None:
                        break
                    if line == "":
                        # EOF/tty closed
                        break

                    # akceptujemy tylko „goły ENTER”
                    if line.strip() != "":
                        continue

                    with self._ptt_lock:  # type: ignore[attr-defined]
                        active = bool(getattr(self, "ptt_active", False))  # type: ignore[attr-defined]

                    if not active:
                        # ---- START PTT ----
                        with self._ptt_lock:  # type: ignore[attr-defined]
                            self.ptt_active = True  # type: ignore[attr-defined]
                            self._any_audio_since_commit = False  # type: ignore[attr-defined]
                            # reset timera aktywności – start teraz
                            self.last_audio_activity_ts = time.monotonic()  # type: ignore[attr-defined]

                        self._publish_ui_state("hearing")  # type: ignore[attr-defined]

                        # barge-in: przerwij TTS natychmiast
                        self.barge_in_event.set()  # type: ignore[attr-defined]

                        # Beep (opcjonalnie, nieblokująco)
                        try:
                            service_cfg = self.config.get("service", {})  # type: ignore[attr-defined]
                            if service_cfg.get("beep", False):

                                def _do_beep():
                                    try:
                                        from .playback import PlaybackConfig, play_ding

                                        playback_cfg = PlaybackConfig(
                                            **self.config.get("playback", {})  # type: ignore[attr-defined]
                                        )
                                        play_ding(playback_cfg, self.logger)  # type: ignore[attr-defined]
                                    except Exception as _e:
                                        if self._log_limiter.allow(
                                            "ptt.beep.error", _env_int("VOICE_PTT_ERROR_EVERY_MS", 1000)
                                        ):
                                            self.logger.event("ptt.beep.error", error=str(_e))  # type: ignore[attr-defined]

                                threading.Thread(target=_do_beep, name="voice-ptt-beep", daemon=True).start()
                        except Exception as e:
                            if self._log_limiter.allow("ptt.beep.error", _env_int("VOICE_PTT_ERROR_EVERY_MS", 1000)):
                                self.logger.event("ptt.beep.error", error=str(e))  # type: ignore[attr-defined]

                        # Upewnij się, że capture żyje
                        try:
                            th = getattr(self, "_capture_thread", None)  # type: ignore[attr-defined]
                            if not (th and th.is_alive()):
                                th = threading.Thread(
                                    target=self._audio_capture_thread,  # type: ignore[attr-defined]
                                    name="voice-stream-capture",
                                    daemon=True,
                                )
                                th.start()
                                self._capture_thread = th  # type: ignore[attr-defined]
                                if self._log_limiter.allow(
                                    "capture.restart.ptt", _env_int("VOICE_PTT_RESTART_EVERY_MS", 2000)
                                ):
                                    self.logger.event("capture.restart.ptt")  # type: ignore[attr-defined]
                        except Exception as e:
                            if self._log_limiter.allow(
                                "capture.restart.error", _env_int("VOICE_PTT_ERROR_EVERY_MS", 1000)
                            ):
                                self.logger.event("capture.restart.error", error=str(e))  # type: ignore[attr-defined]

                        # Odpal watchdog tury (po starcie PTT)
                        if not getattr(self, "_ptt_watchdog_running", False):  # type: ignore[attr-defined]
                            self._ptt_watchdog_running = True  # type: ignore[attr-defined]
                            threading.Thread(
                                target=self._ptt_watchdog_thread,
                                name="voice-ptt-watchdog",
                                daemon=True,
                            ).start()

                        self.logger.event("ptt.toggle", state="start")  # type: ignore[attr-defined]

                    else:
                        # ---- STOP PTT (manualny) ----
                        with self._ptt_lock:  # type: ignore[attr-defined]
                            self.ptt_active = False  # type: ignore[attr-defined]
                            any_audio = bool(self._any_audio_since_commit)  # type: ignore[attr-defined]

                        # Zdarzenie STOP + czy była mowa
                        self.logger.event(  # type: ignore[attr-defined]
                            "ptt.toggle",
                            state="stop",
                            any_audio=any_audio,
                        )

                        # Jeśli była mowa i jesteśmy połączeni → COMMIT
                        if (
                            any_audio
                            and getattr(self, "_loop", None) is not None  # type: ignore[attr-defined]
                            and getattr(self, "connected", False)  # type: ignore[attr-defined]
                        ):
                            self._schedule_commit()

                        # UI „thinking” aż do response.* (nasłuch przez stream)
                        self._publish_ui_state("thinking")  # type: ignore[attr-defined]
                        with self._ptt_lock:  # type: ignore[attr-defined]
                            self._any_audio_since_commit = False  # type: ignore[attr-defined]

                except Exception as e:
                    # Błąd pętli PTT – pojedyncza linia, limitowana (bez floodu)
                    if self._log_limiter.allow("ptt.keyboard.error", _env_int("VOICE_PTT_ERROR_EVERY_MS", 1000)):
                        self.logger.event("ptt.keyboard.error", error=str(e))  # type: ignore[attr-defined]
                    continue
        finally:
            self.logger.event("ptt.keyboard.exit")  # type: ignore[attr-defined]
