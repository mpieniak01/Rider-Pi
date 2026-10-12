"""Read existing backlight GPIO; never configure GPIO or send SPI commands."""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time

from drivers.lcd.board import lcd_board

_LOCK = threading.Lock()
_CACHE = None


def invalidate():
    global _CACHE
    with _LOCK:
        _CACHE = None


def backlight_status(*, runner=None, clock=time.monotonic):
    global _CACHE
    runner = subprocess.run if runner is None else runner
    try:
        board = lcd_board()
        polarity = os.getenv("FACE_LCD_BL_ACTIVE_HIGH", "1")
        if polarity not in {"0", "1"}:
            raise ValueError("invalid_lcd_backlight_polarity")
        key = (board.bl, polarity, runner)
        with _LOCK:
            if _CACHE and _CACHE[0] == key and 0 <= clock() - _CACHE[1] < 3:
                return dict(_CACHE[2])
            result = _read(board.bl, polarity == "1", runner)
            _CACHE = (key, clock(), result)
            return dict(result)
    except (ValueError, OSError) as error:
        return {"on": None, "power_known": False, "error": str(error)}


def _read(pin, active_high, runner):
    try:
        result = runner(["raspi-gpio", "get", str(pin)], timeout=1, capture_output=True, text=True, check=False)
        level = re.search(r"\blevel=([01])\b", result.stdout)
        output = re.search(r"\bfsel=1\b.*\bfunc=OUTPUT\b", result.stdout)
        if result.returncode or result.stderr.strip() or not level or not output:
            raise ValueError("lcd_gpio_unavailable")
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        return {"on": None, "power_known": False, "error": "lcd_gpio_unavailable"}
    at = time.time()
    return {
        "on": (level.group(1) == "1") == active_high,
        "power_known": True,
        "source": "lcd-backlight-gpio",
        "power_source": "lcd-backlight-gpio",
        "observed_at": at,
        "power_observed_at": at,
        "confirmation": "gpio_level_observed",
        "status_basis": "backlight_gpio",
        "physical_validity": "unverified",
        "error": None,
    }
