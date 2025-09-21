from __future__ import annotations

import math
import os
import random
from typing import Any, Dict


# Easingi – lekkie jak w legacy
def ease_in(t: float) -> float:
    return t * t


def ease_out(t: float) -> float:
    u = 1.0 - t
    return 1.0 - u * u


def ease_in_out(t: float) -> float:
    if t < 0.5:
        return 2.0 * t * t
    u = (t - 0.5) * 2.0
    return 0.5 + 0.5 * (1.0 - (1.0 - u) * (1.0 - u))


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


# Spec: prosty, ale czytelny — Animator blenduje „tracks”
# track = lista segmentów: (start, end, v0, v1, easing_name)
# gdzie start/end to czas względny w [0..duration]
def _seg(start: float, end: float, v0: float, v1: float, easing: str = "lin"):
    return {"t0": start, "t1": end, "v0": v0, "v1": v1, "ease": easing}


# ====== GESTURES API ======


def blink(duration: float = None, hold: float = None, max_close: float = 1.0) -> Dict[str, Any]:
    """Mrugnięcie: szybkie zamknięcie → krótki hold → płynne otwarcie.
    max_close w [0..1]: 1.0 = pełne zamknięcie, 0.6 = pół-mrugnięcie."""
    import os

    duration = float(os.getenv("FACE_GESTURE_BLINK_DUR", str(duration if duration else 0.16)))
    hold = float(os.getenv("FACE_GESTURE_BLINK_HOLD", str(hold if hold else 0.02)))
    # clamp
    if max_close < 0.0:
        max_close = 0.0
    if max_close > 1.0:
        max_close = 1.0

    close_t = max(0.06, min(0.10, duration * 0.55))  # szybkie zamykanie
    open_t = max(0.08, duration - close_t - hold)  # daj czas na „otwarcie” przy 9–10 fps

    v_closed = max_close  # ile zamkniemy powiekę
    v_open = 0.0  # otwarte
    tracks = {
        "eyes.blink": [
            _seg(0.0, close_t, v_open, v_closed, "in"),
            _seg(close_t, close_t + hold, v_closed, v_closed, "lin"),
            _seg(close_t + hold, close_t + hold + open_t, v_closed, v_open, "out"),
        ]
    }
    return {"duration": close_t + hold + open_t, "tracks": tracks, "name": "blink"}


def look(t: float = None, amp: float = None, jitter: float = None) -> Dict[str, Any]:
    """Sakkada źrenic: szybki skok, overshoot, tłumienie + mikro-jitter."""
    t = float(os.getenv("FACE_GESTURE_LOOK_T", str(t if t else 0.55)))
    amp = float(os.getenv("FACE_GESTURE_LOOK_AMP", str(amp if amp else 0.45)))
    jitter = float(os.getenv("FACE_GESTURE_LOOK_JITTER", str(jitter if jitter else 0.02)))

    # cel spojrzenia – losowy kierunek w kole
    theta = random.random() * math.tau
    dx_goal = amp * math.cos(theta)
    dy_goal = amp * math.sin(theta)

    # czasy faz (jak w legacy: sakkada 30–40ms, overshoot 50–70ms, settle reszta)
    t0 = 0.0
    t1 = min(0.04, t * 0.1)  # impuls (skok)
    t2 = t1 + min(0.07, t * 0.14)  # overshoot
    t3 = t  # wygaszanie

    overshoot = 1.10  # 10% poza cel
    settle = 0.96  # końcowa stabilizacja ~96% celu

    def build_track(v_goal: float):
        return [
            _seg(t0, t1, 0.0, v_goal * 0.92, "in"),  # skok do ~92%
            _seg(t1, t2, v_goal * 0.92, v_goal * overshoot, "out"),  # overshoot
            _seg(t2, t3, v_goal * overshoot, v_goal * settle, "in_out"),  # tłumienie
        ]

    tracks = {
        "eyes.dx": build_track(dx_goal),
        "eyes.dy": build_track(dy_goal),
    }

    # mikrosakkady na końcu – króciutkie, prawie niewidoczne, ale „ożywiają”
    if jitter > 0.0:
        jt = min(0.10, t * 0.18)
        jx = dx_goal * (jitter * 0.65)
        jy = dy_goal * (jitter * 0.65)
        tracks["eyes.dx"] += [
            _seg(t3, t3 + jt * 0.5, dx_goal * settle, dx_goal * (settle + jx), "out"),
            _seg(t3 + jt * 0.5, t3 + jt, dx_goal * (settle + jx), dx_goal * settle, "in"),
        ]
        tracks["eyes.dy"] += [
            _seg(t3, t3 + jt * 0.5, dy_goal * settle, dy_goal * (settle + jy), "out"),
            _seg(t3 + jt * 0.5, t3 + jt, dy_goal * (settle + jy), dy_goal * settle, "in"),
        ]

    return {"duration": t + min(0.12, t * 0.2), "tracks": tracks, "name": "look"}


# Rejestr
GESTURES = {
    "blink": blink,
    "look": look,
}
