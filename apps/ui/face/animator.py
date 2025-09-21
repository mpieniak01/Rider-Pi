from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .model import FaceState


def _ease(kind: str, t01: float) -> float:
    if kind in ("in", "ease_in"):
        return t01 * t01
    if kind in ("out", "ease_out"):
        u = 1.0 - t01
        return 1.0 - u * u
    if kind in ("in_out", "ease_in_out"):
        if t01 < 0.5:
            return 2.0 * t01 * t01
        u = (t01 - 0.5) * 2.0
        return 0.5 + 0.5 * (1.0 - (1.0 - u) * (1.0 - u))
    return t01  # lin


@dataclass
class _Active:
    spec: dict[str, Any]
    t0: float
    t1: float


class Animator:
    """
    Prosty animator „tracks/segments”:
      spec = {
        "duration": float,
        "tracks": {
          "eyes.blink": [{"t0":0.0,"t1":0.08,"v0":0.0,"v1":1.0,"ease":"in"}, ...],
          ...
        }
      }
    - Każdy segment działa w oknie [t0..t1] względem startu animacji.
    - Jeśli FPS jest niski i przeskoczymy jakiś segment, „snapujemy” do końcowego v1
      po upływie całej animacji, żeby nie utknąć np. z zamkniętym okiem.
    """

    def __init__(self):
        self.state = FaceState()
        self._actives: list[_Active] = []

    def start(self, spec: dict[str, Any], prio: int = 10, mode: str = "blend") -> None:
        dur = float(spec.get("duration", 0.2))
        now = time.time()
        self._actives.append(_Active(spec=spec, t0=now, t1=now + dur))

    def _apply_track_segment(self, path: str, seg: dict[str, Any], now: float, t0: float) -> bool:
        s0, s1 = float(seg["t0"]), float(seg["t1"])
        t_abs0, t_abs1 = t0 + s0, t0 + s1
        if now < t_abs0 or now > t_abs1:
            return False
        # pozycja 0..1 w obrębie segmentu
        k = (now - t_abs0) / max(1e-6, (t_abs1 - t_abs0))
        k = max(0.0, min(1.0, k))
        k = _ease(seg.get("ease", "lin"), k)
        v = float(seg["v0"]) + (float(seg["v1"]) - float(seg["v0"])) * k

        # zapis do modelu (obsługa ścieżek typu "eyes.blink")
        node = self.state
        parts = path.split(".")
        for p in parts[:-1]:
            node = getattr(node, p)
        setattr(node, parts[-1], v)
        return True

    def _apply_track_final(self, path: str, segs: list[dict[str, Any]]) -> None:
        """Ustaw końcowe v1 ostatniego segmentu danego tracku."""
        if not segs:
            return
        last = segs[-1]
        v = float(last.get("v1", 0.0))
        node = self.state
        parts = path.split(".")
        for p in parts[:-1]:
            node = getattr(node, p)
        setattr(node, parts[-1], v)

    def tick(self) -> FaceState:
        now = time.time()

        still_active: list[_Active] = []
        for a in self._actives:
            spec = a.spec
            tracks: dict[str, list[dict[str, Any]]] = spec.get("tracks", {})

            if now >= a.t1:
                # Animacja zakończona → „snap” do stanów końcowych wszystkich tracków
                for path, segs in tracks.items():
                    self._apply_track_final(path, segs)
                # nie dokładamy do still_active → znika po tym ticku
                continue

            # W trakcie trwania animacji: stosujemy segmenty, które trafiały w okna czasowe
            for path, segs in tracks.items():
                # Jeśli przeskoczyliśmy segmenty (niski FPS), nic się nie nałoży – to OK.
                for seg in segs:
                    self._apply_track_segment(path, seg, now, a.t0)

            still_active.append(a)

        self._actives = still_active
        return self.state
