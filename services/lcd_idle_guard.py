#!/usr/bin/env python3
"""Automatyczne wygaszanie LCD 2" przy bezczynności (oszczędzanie energii)."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from services.api_core import compat as C, resource_diag

LOG = logging.getLogger("lcd.idle_guard")

CHECK_INTERVAL_S = float(os.getenv("LCD_IDLE_CHECK_INTERVAL", "20"))
IDLE_OFF_AFTER_S = float(os.getenv("LCD_IDLE_OFF_AFTER_S", "45"))
ENABLED = os.getenv("LCD_IDLE_GUARD", "1").lower() not in {"0", "false", "off"}

_thread: threading.Thread | None = None
_stop_evt = threading.Event()
_last_busy_ts = time.time()
_last_action_ts = 0.0
_power_state: bool | None = None  # True=on, False=auto-off, None=unknown


def _update_lcd_state(
    *, on: bool | None = None, snapshot: dict[str, Any] | None = None, auto_off_ts: float | None = None
) -> None:
    """Uzupełnij globalny stan LCD widoczny w endpointach (/healthz)."""
    try:
        lcd = C.LAST_CAMERA["lcd"]
    except Exception:
        return

    if snapshot is not None:
        lcd["presenting"] = not snapshot.get("free", False)
        lcd["holders"] = snapshot.get("holders") or []
        lcd["checked_at"] = snapshot.get("checked_at") or time.time()

    if on is not None:
        lcd["on"] = bool(on)
        if not on:
            lcd["active"] = False
            lcd["presenting"] = False

    if auto_off_ts is not None:
        lcd["auto_off_ts"] = auto_off_ts


def _poll_once(now: float | None = None) -> None:
    """Wykonaj pojedyncze sprawdzenie LCD; wywoływane cyklicznie w tle."""
    global _last_busy_ts, _last_action_ts, _power_state

    if not ENABLED:
        return

    if now is None:
        now = time.time()

    try:
        snapshot = resource_diag.inspect("lcd")
    except Exception as exc:  # noqa: BLE001
        LOG.warning("LCD idle guard: inspect failed: %s", exc)
        return

    busy = not snapshot.get("free", False)
    _update_lcd_state(snapshot=snapshot)

    if busy:
        _last_busy_ts = now
        _power_state = True
        _update_lcd_state(on=True)
        return

    if snapshot.get("error"):
        return

    idle_for = now - _last_busy_ts
    already_off = _power_state is False
    if idle_for < IDLE_OFF_AFTER_S or already_off:
        return

    if (now - _last_action_ts) < CHECK_INTERVAL_S:
        return

    try:
        result = resource_diag.release("lcd")
    except Exception as exc:  # noqa: BLE001
        LOG.warning("LCD idle guard: off failed: %s", exc)
        _last_action_ts = now
        return

    _last_action_ts = now
    if result.get("ok"):
        _power_state = False
        _update_lcd_state(on=False, auto_off_ts=now)
        LOG.info("LCD idle guard: turned off LCD after %.1fs idle", idle_for)
    else:
        LOG.warning("LCD idle guard: off command failed: %s", result)


def _loop() -> None:
    if not ENABLED:
        LOG.info("LCD idle guard disabled (LCD_IDLE_GUARD=0)")
        return

    LOG.info(
        "LCD idle guard started (interval=%.1fs, idle_off=%.1fs)",
        CHECK_INTERVAL_S,
        IDLE_OFF_AFTER_S,
    )
    while not _stop_evt.wait(CHECK_INTERVAL_S):
        _poll_once()
    LOG.info("LCD idle guard stopped")


def start() -> bool:
    """Uruchom wątek strażnika (idempotentnie)."""
    global _thread, _stop_evt, _last_busy_ts, _power_state
    if not ENABLED:
        return False
    if _thread and _thread.is_alive():
        return False

    _stop_evt = threading.Event()
    _last_busy_ts = time.time()
    _power_state = None
    _thread = threading.Thread(target=_loop, name="lcd-idle-guard", daemon=True)
    _thread.start()
    return True


def stop(timeout: float = 0.0) -> None:
    """Zatrzymaj wątek strażnika (na potrzeby testów)."""
    global _thread
    _stop_evt.set()
    if _thread and timeout > 0:
        _thread.join(timeout)
    _thread = None


__all__ = ["start", "stop", "_poll_once"]
