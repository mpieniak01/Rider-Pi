#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apps/motion/xgo_adapter.py — cienka warstwa nad biblioteką XGO (CM4/Rider)

Cel:
- Zapewnić jednolite, bezpieczne API do ruchu/LED/baterii bez wciągania monolitu OEM.
- Domyślnie NIE uruchamia fizycznego ruchu (MOTION_ENABLE=0). Włączenie: MOTION_ENABLE=1.

Wspierane środowisko:
- Pakiet 'xgolib' (wchodzi m.in. z xgodoglib); łagodnie z fallbackami metod.

Publiczne metody (bez żadnych side-effectów, jeśli brak HW/ENABLE):
- ok() -> bool
- stop()
- drive(dir: "forward"|"backward", speed: 0..1, dur: float|None = None, *, block=False)
- spin(dir: "left"|"right", speed: 0..1, dur: float|None = None, deg: float|None = None, *, block=False)
- action(name: str)  # np. "sit"|"stand"|"wave"|"default"
- led(idx: int, rgb: tuple[int,int,int])
- battery() -> float|None   # 0..1 (ułamkowo), None jeśli brak odczytu
- imu() -> dict|None        # {"roll":..,"pitch":..,"yaw":..} lub None
- available_methods() -> list[str]
"""

from __future__ import annotations
import os, time
from typing import Optional, Iterable

# --- Import biblioteki XGO (łagodnie) ---
try:
    from xgolib import XGO  # typowe wejście
    _HAS_XGO = True
except Exception:
    XGO = None  # type: ignore
    _HAS_XGO = False

# --- Konfiguracja przez ENV ---
XGO_PORT    = os.getenv("XGO_PORT", "/dev/ttyAMA0")
XGO_VERSION = os.getenv("XGO_VERSION", "xgorider")  # xgomini|xgolite|xgorider
MOTION_ENABLE = os.getenv("MOTION_ENABLE", "0") == "1"  # domyślnie OFF (bezpiecznie)

# Maks. czas bloku przy block=True
_MAX_BLOCK_S = 5.0


class XgoAdapter:
    def __init__(self, port: str = XGO_PORT, version: str = XGO_VERSION):
        self._dog = None
        self._port = port
        self._version = version

        if not _HAS_XGO:
            return  # brak biblioteki — tryb stub

        # Inicjalizacja i łagodna autodetekcja wariantu FW (M/L/R)
        try:
            self._dog = XGO(port=port, version=version)
            rf = getattr(self._dog, "read_firmware", None)
            if callable(rf):
                try:
                    fw = rf()
                    if isinstance(fw, str) and fw:
                        lead = fw[0].upper()
                        if lead == "M" and version != "xgomini":
                            self._dog = XGO(port=port, version="xgomini")
                        elif lead == "L" and version != "xgolite":
                            self._dog = XGO(port=port, version="xgolite")
                        elif lead == "R" and version != "xgorider":
                            self._dog = XGO(port=port, version="xgorider")
                except Exception:
                    pass
        except Exception:
            self._dog = None  # nie dało się zainicjalizować

    # --- podstawy ---
    def ok(self) -> bool:
        """Czy biblioteka/urządzenie są dostępne."""
        return self._dog is not None

    def available_methods(self) -> list[str]:
        if not self.ok():
            return []
        return sorted([m for m in dir(self._dog) if not m.startswith("_")])

    def _call(self, name: str, *args, **kwargs) -> bool:
        """Wywołaj metodę urządzenia, jeśli istnieje; zwróć True przy sukcesie."""
        if not self.ok():
            return False
        fn = getattr(self._dog, name, None)
        if not callable(fn):
            return False
        try:
            fn(*args, **kwargs)
            return True
        except Exception:
            return False

    # --- bezruch / stop ---
    def stop(self) -> None:
        """Natychmiastowy STOP (bez względu na MOTION_ENABLE — bezpieczne)."""
        if not self.ok():
            return
        # preferowane 'stop', fallback 'action(0)'
        if not self._call("stop"):
            self._call("action", 0)

    # --- LED / telemetria ---
    def led(self, idx: int, rgb: Iterable[int]) -> None:
        """Ustaw LED (nie wymaga MOTION_ENABLE). idx: 0/1 lub oba."""
        if not self.ok():
            return
        r, g, b = list(rgb)[:3] if rgb else (0, 0, 0)
        self._call("rider_led", int(idx), [int(r), int(g), int(b)])

    def battery(self) -> Optional[float]:
        """Zwraca poziom baterii w skali 0..1 (None, jeśli brak odczytu)."""
        if not self.ok():
            return None
        try:
            v = getattr(self._dog, "read_battery", None)
            if callable(v):
                raw = v()
                # spotyka się 0..100 lub 0..1
                try:
                    f = float(raw)
                    if f > 1.0:
                        f = f / 100.0
                    return max(0.0, min(1.0, f))
                except Exception:
                    return None
        except Exception:
            pass
        return None

    def imu(self) -> Optional[dict]:
        """Zwraca orientację, jeśli dostępna: {'roll':.., 'pitch':.., 'yaw':..}."""
        if not self.ok():
            return None
        try:
            fn = getattr(self._dog, "imu", None)
            if callable(fn):
                data = fn()
                if isinstance(data, (tuple, list)) and len(data) >= 3:
                    roll, pitch, yaw = data[:3]
                    return {"roll": float(roll), "pitch": float(pitch), "yaw": float(yaw)}
        except Exception:
            pass
        return None

    # --- prymitywy ruchu ---
    def drive(self, dir: str, speed: float, dur: Optional[float] = None, *, block: bool = False) -> None:
        """
        Jazda liniowa (forward/backward). Jeśli biblioteka wspiera 't', przekaże 'dur';
        w przeciwnym razie uruchomi jazdę i ewentualnie zatrzyma po 'dur' (gdy block=True).
        """
        if not self.ok():
            return
        if not MOTION_ENABLE:
            return  # ochrona

        d = (dir or "").lower()
        s = max(0.0, min(1.0, float(speed)))
        t = float(dur) if dur is not None else 0.0

        if d not in ("forward", "backward"):
            return

        # Rider-spec → ogólne → bardzo ogólne
        called = False
        if d == "forward":
            called = self._call("rider_move_x", +s) or self._call("move", vx=+s, vy=0, wz=0, t=t) or self._call("forward")
        else:
            called = self._call("rider_move_x", -s) or self._call("move", vx=-s, vy=0, wz=0, t=t) or self._call("back")

        if block and t > 0 and called:
            time.sleep(min(t, _MAX_BLOCK_S))
            self.stop()

    def spin(self, dir: str, speed: float, dur: Optional[float] = None,
             deg: Optional[float] = None, *, block: bool = False) -> None:
        """
        Obrót w miejscu (left/right). Priorytet: rider_turn → turn(wz,t) → turnleft/turnright.
        """
        if not self.ok():
            return
        if not MOTION_ENABLE:
            return  # ochrona

        d = (dir or "").lower()
        s = max(0.0, min(1.0, float(speed)))
        t = float(dur) if dur is not None else 0.0
        wz = +s if d == "left" else -s

        if d not in ("left", "right"):
            return

        called = self._call("rider_turn", wz) or self._call("turn", wz=wz, t=t) \
                 or (self._call("turnleft") if d == "left" else self._call("turnright"))

        if block and t > 0 and called:
            time.sleep(min(t, _MAX_BLOCK_S))
            self.stop()

    def action(self, name: str) -> None:
        """
        Akcje/pozy (best-effort): preferuje rider_action(name), fallback na action(id).
        Dopuszczalne nazwy: 'sit','stand','wave','default'.
        """
        if not self.ok():
            return
        if not MOTION_ENABLE:
            return  # ochrona

        n = (name or "").lower().strip()
        if not n:
            return

        if self._call("rider_action", n):
            return

        # Mapowanie znanych nazw na ID (przykładowe; może różnić się FW)
        MAP = {"default": 0, "stand": 1, "sit": 2, "wave": 6}
        if n in MAP:
            self._call("action", MAP[n])

