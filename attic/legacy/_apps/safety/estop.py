#!/usr/bin/env python3
import os
from pathlib import Path

BASE = Path("/home/pi/robot")
FLAGS = BASE / "data" / "flags"
FLAGS.mkdir(parents=True, exist_ok=True)

MOTION_ENABLE_FLAG = FLAGS / "motion.enable"
ESTOP_FLAG = FLAGS / "estop.on"

# GPIO (opcjonalnie): ustaw ESTOP_GPIO=17 (BCM). Aktywne niskim stanem.
GPIO_PIN = int(os.getenv("ESTOP_GPIO", "-1"))
_ACTIVE_LOW = True
_gpio_ok = False

try:
    if GPIO_PIN >= 0:
        import RPi.GPIO as GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(GPIO_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP if _ACTIVE_LOW else GPIO.PUD_DOWN)
        _gpio_ok = True
except Exception:
    _gpio_ok = False  # brak biblioteki lub sprzętu → fallback

def estop_triggered() -> bool:
    """
    E-Stop aktywny jeśli:
      1) plik-flag 'estop.on' istnieje, LUB
      2) fizyczny przycisk na GPIO (jeśli skonfigurowany), LUB
      3) ESTOP=1 w środowisku (tylko do testów poza systemd).
    """
    if ESTOP_FLAG.exists():
        return True
    if _gpio_ok:
        val = GPIO.input(GPIO_PIN)
        return (val == 0) if _ACTIVE_LOW else (val == 1)
    return os.getenv("ESTOP", "0") == "1"

def motion_enabled() -> bool:
    """
    Ruch dozwolony, gdy:
      - MOTION_ENABLE=1 w środowisku (np. gdy uruchamiasz ręcznie), LUB
      - istnieje plik-flag 'motion.enable'.
    """
    if os.getenv("MOTION_ENABLE", "0") == "1":
        return True
    return MOTION_ENABLE_FLAG.exists()

def safe_speed(v: float, limit: float = 0.6) -> float:
    """Clamp prędkości."""
    return max(-limit, min(limit, v))
