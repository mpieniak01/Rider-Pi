"""Hardware-free compatibility reads; flags or ENV never grant motion consent."""

from __future__ import annotations

import math
import os
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
FLAGS = Path(os.getenv("MOTION_FLAGS_DIR", str(BASE / "data" / "flags")))
MOTION_ENABLE_FLAG = FLAGS / "motion.enable"  # legacy, deliberately not an authority
ESTOP_FLAG = FLAGS / "estop.on"
_gpio = None
_gpio_failed = False


def external_estop(*, include_flag: bool = True) -> bool:
    """Read configured E-Stop; a failed configured GPIO inhibits motion."""
    global _gpio, _gpio_failed
    if (include_flag and ESTOP_FLAG.exists()) or os.getenv("ESTOP", "0") == "1":
        return True
    try:
        pin = int(os.getenv("ESTOP_GPIO", "-1"))
    except ValueError:
        return True
    if pin < 0:
        return False
    if _gpio_failed:
        return True
    try:
        if _gpio is None:
            import RPi.GPIO as gpio

            gpio.setmode(gpio.BCM)
            gpio.setup(pin, gpio.IN, pull_up_down=gpio.PUD_UP)
            _gpio = gpio
        return _gpio.input(pin) == 0
    except Exception:
        _gpio_failed = True
        return True


def estop_triggered() -> bool:
    return external_estop()


def motion_enabled() -> bool:
    from apps.safety.state import read_status

    return bool(read_status().get("can_move", False))


def safe_speed(v: float, limit: float = 0.6) -> float:
    try:
        value = float(v)
        ceiling = abs(float(limit))
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(value) or not math.isfinite(ceiling):
        return 0.0
    return max(-ceiling, min(ceiling, value))
