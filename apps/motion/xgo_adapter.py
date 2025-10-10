#!/usr/bin/env python3
"""
apps/motion/xgo_adapter.py — cienka warstwa nad biblioteką XGO (CM4/Rider)

DEPRECATED: This module is kept for backward compatibility.
Please use drivers.xgo.XgoAdapter instead.

Cel:
- Jednolite, bezpieczne API do ruchu/LED/baterii/IMU + parę udogodnień.
- Domyślnie NIE uruchamia fizycznego ruchu (MOTION_ENABLE=0). Włączenie: MOTION_ENABLE=1.

Wspierane środowisko:
- Pakiet 'xgolib' (wchodzi m.in. z xgodoglib); łagodne fallbacki metod.

Publiczne metody (best-effort, brak side-effectów gdy brak HW/ENABLE):
- ok() -> bool
- available_methods() -> list[str]
- stop()
- set_stabilization(on: bool)
- enable_balance(on: bool)
- set_height(h: int)
- drive(dir: "forward"|"backward", speed: 0..1, dur: float|None = None, *, block=False)
- spin(dir: "left"|"right", speed: 0..1, dur: float|None = None, deg: float|None = None, *, block=False)
- action(name: str)   # 'sit'|'stand'|'wave'|'default'
- led(idx: int, rgb: tuple[int,int,int])
- battery() -> float|None   # 0..1, None gdy brak odczytu
- imu() -> dict|None        # {"roll":..,"pitch":..,"yaw":..} lub None
"""

from __future__ import annotations

# Re-export from new location
from drivers.xgo import XgoAdapter

__all__ = ["XgoAdapter"]
