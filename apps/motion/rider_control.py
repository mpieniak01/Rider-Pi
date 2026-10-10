#!/usr/bin/env python3
"""
apps/motion/rider_control.py — bezpieczne mikro-impulsy ruchu dla Rider-Pi

Warstwa nad XgoAdapter:
- Dedup komend (cooldown), parametry z ENV, mikro-ruchy (impuls + STOP).
- NIE obchodzi ochrony MOTION_ENABLE — tę egzekwuje XgoAdapter.

ENV (opcjonalne):
  RIDER_PULSE=0.30       # czas impulsu (s)
  RIDER_SPEED_LIN=0.10   # 0..1 (skalowane do 1..12)
  RIDER_SPEED_YAW=0.10   # 0..1 (skalowane do 1..12)
  RIDER_COOLDOWN=0.35    # min. odstęp między identycznymi komendami (s)
  RIDER_IMU=1            # 1=autobalans ON, 0=OFF
  XGO_PORT=/dev/ttyAMA0
  XGO_VERSION=xgorider
  MOTION_ENABLE=1        # włącz fizyczny ruch!
"""

from __future__ import annotations

import os
import threading
import time

from drivers.xgo import XgoAdapter


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except Exception:
        return default


class RiderMotion:
    def __init__(self):
        self.PULSE = _env_float("RIDER_PULSE", 0.30)
        self.SPEED_LIN = _env_float("RIDER_SPEED_LIN", 0.10)  # frakcja 0..1
        self.SPEED_YAW = _env_float("RIDER_SPEED_YAW", 0.10)  # frakcja 0..1
        self.COOLDOWN = _env_float("RIDER_COOLDOWN", 0.35)
        self.IMU_ON = _env_int("RIDER_IMU", 1)

        self._ada = XgoAdapter()
        self._lock = threading.Lock()
        self._last_cmd = None
        self._last_ts = 0.0

        # Construction has no balance/height/movement side effects. This legacy
        # direct interface cannot acquire the executor's operator consent lease.

    def _ok(self, key: str) -> bool:
        """Anty-powielanie tej samej komendy (np. 3x ten sam transcript)."""
        now = time.monotonic()
        with self._lock:
            if self._last_cmd == key and (now - self._last_ts) < self.COOLDOWN:
                print(f"[DEDUP] skip {key}")
                return False
            self._last_cmd = key
            self._last_ts = now
            return True

    # --- API wysokiego poziomu ---
    def stop(self) -> None:
        from services.safety_contract import request_stop

        request_stop()

    def forward(self) -> None:
        raise PermissionError("legacy direct motion retired; use operator consent API")

    def backward(self) -> None:
        raise PermissionError("legacy direct motion retired; use operator consent API")

    def left(self) -> None:
        raise PermissionError("legacy direct motion retired; use operator consent API")

    def right(self) -> None:
        raise PermissionError("legacy direct motion retired; use operator consent API")


# Szybki tryb demo z CLI: python3 -m apps.motion.rider_control
if __name__ == "__main__":
    raise SystemExit("Automatic actuator demo retired. Use the explicit operator test workflow.")
