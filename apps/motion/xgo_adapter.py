#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apps/motion/xgo_adapter.py — cienka warstwa nad biblioteką XGO (CM4/Rider)

Cel:
- Jednolite, bezpieczne API do ruchu/LED/baterii/IMU + parę udogodnień.
- Domyślnie NIE uruchamia fizycznego ruchu (MOTION_ENABLE=0). Włączenie: MOTION_ENABLE=1.

Wspierane środowisko:
- Pakiet 'xgolib' (wchodzi m.in. z xgodoglib); łagodne fallbacki metod.

Publiczne metody (bez side-effectów, jeśli brak HW/ENABLE):
- ok() -> bool
- available_methods() -> list[str]
- stop()
- set_stabilization(on: bool)         # ogólne imu(1/0), gdy rider_balance_* nie ma
- enable_balance(on: bool)            # preferuj rider_balance_roll(1/0), fallback imu(1/0)
- set_height(h: int)                  # bezpieczny clamp (70..115)
- drive(dir: "forward"|"backward", speed: 0..1, dur: float|None = None, *, block=False)
- spin(dir: "left"|"right", speed: 0..1, dur: float|None = None, deg: float|None = None, *, block=False)
- action(name: str)                   # 'sit'|'stand'|'wave'|'default'
- led(idx: int, rgb: tuple[int,int,int])
- battery() -> float|None             # 0..1, None gdy brak odczytu
- imu() -> dict|None                  # {"roll":..,"pitch":..,"yaw":..} lub None
"""

from __future__ import annotations
import os
import time
from typing import Optional, Iterable

# ── Import biblioteki XGO (łagodnie) ─────────────────────────────────────────
try:
    from xgolib import XGO   # typowe wejście
    _HAS_XGO = True
except Exception:
    XGO = None  # type: ignore
    _HAS_XGO = False

# ── Konfiguracja przez ENV ───────────────────────────────────────────────────
XGO_PORT        = os.getenv("XGO_PORT", "/dev/ttyAMA0")
XGO_VERSION     = os.getenv("XGO_VERSION", "xgorider")  # xgomini|xgolite|xgorider
MOTION_ENABLE   = os.getenv("MOTION_ENABLE", "0") == "1"  # domyślnie OFF (bezpiecznie)
_DEFAULT_PULSE  = float(os.getenv("RIDER_PULSE", "0.30"))  # domyślny czas impulsu (s)

# Skala „kroków” w funkcjach ogólnych (np. move_x/turn) – mała, delikatna
_MIN_STEP = 1
_MAX_STEP = 12

# Skala dla legacy `turnleft/turnright` (wg vendor UI; duża, wyraźna)
_TURN_FALLBACK_MIN = int(os.getenv("TURN_FALLBACK_MIN", "20"))
_TURN_FALLBACK_MAX = int(os.getenv("TURN_FALLBACK_MAX", "70"))

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

    # ── podstawy ──────────────────────────────────────────────────────────────
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

    # ── STOP (zawsze bezpieczny) ─────────────────────────────────────────────
    def stop(self) -> None:
        """Natychmiastowy STOP (bez względu na MOTION_ENABLE)."""
        if not self.ok():
            return
        if not self._call("stop"):
            self._call("action", 0)

    # ── LED / telemetria ─────────────────────────────────────────────────────
    def led(self, idx: int, rgb: Iterable[int]) -> None:
        """Ustaw LED (nie wymaga MOTION_ENABLE). idx: 0/1."""
        if not self.ok():
            return
        r, g, b = list(rgb)[:3] if rgb else (0, 0, 0)
        self._call("rider_led", int(idx), [int(r), int(g), int(b)])

    def battery(self) -> Optional[float]:
        """Zwraca poziom baterii w skali 0..1 (None, jeśli brak odczytu)."""
        if not self.ok():
            return None
        try:
            v = getattr(self._dog, "rider_read_battery", None) or getattr(self._dog, "read_battery", None)
            if callable(v):
                raw = v()
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
        """Zwraca orientację, jeśli dostępna: {'roll':..,'pitch':..,'yaw':..}."""
        if not self.ok():
            return None
        try:
            r = getattr(self._dog, "rider_read_roll", None) or getattr(self._dog, "read_roll", None)
            p = getattr(self._dog, "rider_read_pitch", None) or getattr(self._dog, "read_pitch", None)
            y = getattr(self._dog, "rider_read_yaw", None) or getattr(self._dog, "read_yaw", None)
            if callable(r) and callable(p) and callable(y):
                return {"roll": float(r()), "pitch": float(p()), "yaw": float(y())}
        except Exception:
            pass
        return None

    def set_stabilization(self, on: bool) -> None:
        """Ogólne imu(1/0) – tam gdzie brak rider_balance_*."""
        if not self.ok():
            return
        try:
            fn = getattr(self._dog, "imu", None)
            if callable(fn):
                fn(1 if on else 0)
        except Exception:
            pass

    def enable_balance(self, on: bool) -> None:
        """Włącza/wyłącza aktywny balans (preferuj rider_balance_roll, fallback imu)."""
        if not self.ok():
            return
        if not self._call("rider_balance_roll", 1 if on else 0):
            self._call("imu", 1 if on else 0)

    def set_height(self, h: int) -> None:
        """Ustaw wysokość zawieszenia (bezpieczny clamp)."""
        if not self.ok():
            return
        try:
            h = int(h)
        except Exception:
            return
        h = max(70, min(115, h))  # bezpieczne widełki
        self._call("rider_height", h)

    # ── prymitywy ruchu ──────────────────────────────────────────────────────
    @staticmethod
    def _clamp01(x: float) -> float:
        try:
            f = float(x)
        except Exception:
            return 0.0
        return 0.0 if f < 0.0 else 1.0 if f > 1.0 else f

    def _scale_to_step(self, f: float) -> int:
        """Skaluj 0..1 → 1..12 (delikatnie)."""
        s = self._clamp01(f)
        step = int(round(_MIN_STEP + s * (_MAX_STEP - _MIN_STEP)))
        return max(_MIN_STEP, min(_MAX_STEP, step))

    def drive(self, dir: str, speed: float, dur: Optional[float] = None, *, block: bool = False) -> None:
        """
        Jazda liniowa (forward/backward).
        Używa impulsu (runtime), po którym domyślnie STOP (bez block=True).
        speed: 0..1 (skalowane do kroków API, ~1..12)
        dur: czas impulsu w sekundach (domyślnie RIDER_PULSE).
        """
        if not self.ok() or not MOTION_ENABLE:
            return

        d = (dir or "").lower()
        if d not in ("forward", "backward"):
            return

        step = self._scale_to_step(speed)
        t = float(dur) if dur is not None else _DEFAULT_PULSE

        # Rider-spec → ogólne → bardzo ogólne
        if d == "forward":
            called = self._call("rider_move_x", +step, t) \
                  or self._call("move_x", +step, t) \
                  or self._call("forward", +step)
        else:
            called = self._call("rider_move_x", -step, t) \
                  or self._call("move_x", -step, t) \
                  or self._call("back", +step)

        if called:
            if block and t > 0:
                time.sleep(min(t, _MAX_BLOCK_S))
                self.stop()
            else:
                self.stop()

    def spin(self, dir: str, speed: float, dur: Optional[float] = None,
             deg: Optional[float] = None, *, block: bool = False) -> None:
        """
        Obrót w miejscu (left/right).
        Priorytet: turn_by(theta) → rider_turn(step, t) → turn(step, t) → turnleft/right(duży_krok)

        Parametry środowiskowe (ENV):
          RIDER_TURN_THETA   - domyślny kąt [deg] gdy deg=None (np. 22)
          RIDER_TURN_MINTIME - minimalny czas ruchu [s] (np. 0.45; fallback dla dur=None)
          RIDER_TURN_VYAW    - prędkość bazowa yaw (np. 16)
          RIDER_TURN_K       - wzmocnienie kontrolera (np. 0.08)
          RIDER_TURN_FLIP    - 0/1 odwrócenie znaku yaw (dopasowanie do FW)
          TURN_FALLBACK_MIN  - min krok dla turnleft/right (np. 20)
          TURN_FALLBACK_MAX  - max krok dla turnleft/right (np. 70)
        """
        if not self.ok() or not MOTION_ENABLE:
            return

        d = (dir or "").lower()
        if d not in ("left", "right"):
            return

        # Parametry z ENV (z sensownymi domyślnymi)
        try:    theta_env = float(os.getenv("RIDER_TURN_THETA", "14"))
        except: theta_env = 14.0
        try:    mintime_env = float(os.getenv("RIDER_TURN_MINTIME", os.getenv("RIDER_PULSE", "0.30")))
        except: mintime_env = _DEFAULT_PULSE
        try:    vyaw = int(os.getenv("RIDER_TURN_VYAW", "16"))
        except: vyaw = 16
        try:    k_gain = float(os.getenv("RIDER_TURN_K", "0.08"))
        except: k_gain = 0.08
        flip = os.getenv("RIDER_TURN_FLIP", "0") == "1"

        # Krok dla rider_turn/turn (delikatny, 1..12)
        step_small = max(2, self._scale_to_step(speed))
        val_small  = +step_small if d == "left" else -step_small
        t_eff = float(dur) if dur is not None else mintime_env

        # Kąt dla turn_by (stopnie); dodatni = lewo (po flip może zmienić znak)
        theta = abs(deg) if isinstance(deg, (int, float)) and deg else theta_env
        if (d == "right" and not flip) or (d == "left" and flip):
            theta = -theta

        # 1) Precyzyjnie: turn_by(theta, mintime, vyaw, k)
        called = self._call("turn_by", theta, max(0.25, t_eff), vyaw, k_gain)

        # 2) rider_turn(step, t)
        if not called:
            called = self._call("rider_turn", val_small, t_eff)

        # 3) turn(step, t)
        if not called:
            called = self._call("turn", val_small, t_eff)

        # 4) legacy turnleft/right — duża skala kroku (20..70), jak u vendora
        if not called:
            s = self._clamp01(speed)
            turn_step = int(round(_TURN_FALLBACK_MIN + s * (_TURN_FALLBACK_MAX - _TURN_FALLBACK_MIN)))
            called = self._call("turnleft", turn_step) if d == "left" else self._call("turnright", turn_step)

        if called:
            if block and t_eff > 0:
                time.sleep(min(t_eff, _MAX_BLOCK_S))
                self.stop()
            else:
                self.stop()

    def action(self, name: str) -> None:
        """
        Akcje/pozy (best-effort): preferuje rider_action(id), fallback na action(id).
        Dopuszczalne nazwy: 'sit','stand','wave','default'.
        """
        if not self.ok() or not MOTION_ENABLE:
            return
        n = (name or "").lower().strip()
        if not n:
            return
        MAP = {"default": 0, "stand": 1, "sit": 2, "wave": 6}
        if n in MAP and self._call("rider_action", MAP[n], False):
            return
        if n in MAP:
            self._call("action", MAP[n], False)

