from __future__ import annotations

import time
from dataclasses import dataclass

from .model import FaceState


@dataclass
class Keyframe:
    t: float
    params: dict[str, float]  # np. {"eyes.blink": 1.0} albo {"eyes.dx": 0.5}


@dataclass
class GestureSpec:
    name: str
    channel: str  # "eyes" | "brows" | "mouth" | "head"
    frames: list[Keyframe]
    fade_in: float = 0.06
    fade_out: float = 0.06


def _ease(a: float) -> float:
    # smoothstep
    a = 0.0 if a < 0.0 else 1.0 if a > 1.0 else a
    return a * a * (3 - 2 * a)


class Animator:
    """Miksuje aktywne gesty per kanał i aktualizuje FaceState."""

    def __init__(self):
        self.state = FaceState()
        self._layers: dict[str, dict] = {}  # channel -> {spec, t0, prio}
        self._now = time.time()

    def start(self, spec: GestureSpec, prio: int = 10, mode: str = "blend") -> None:
        ch = spec.channel
        if mode == "override":
            self._layers.pop(ch, None)
        self._layers[ch] = {"spec": spec, "t0": time.time(), "prio": prio}

    def stop(self, channel: str | None = None) -> None:
        if channel:
            self._layers.pop(channel, None)
        else:
            self._layers.clear()

    # ---- helpers ----
    def _params_at(self, spec: GestureSpec, t: float) -> dict[str, float]:
        fr = spec.frames
        if not fr:
            return {}
        if t <= fr[0].t:
            return fr[0].params
        if t >= fr[-1].t:
            return fr[-1].params
        i = 0
        while i < len(fr) - 1 and not (fr[i].t <= t <= fr[i + 1].t):
            i += 1
        a = (t - fr[i].t) / max(1e-6, (fr[i + 1].t - fr[i].t))
        a = _ease(a)
        out: dict[str, float] = {}
        keys = set(fr[i].params) | set(fr[i + 1].params)
        for k in keys:
            v0 = fr[i].params.get(k, 0.0)
            v1 = fr[i + 1].params.get(k, v0)
            out[k] = (1 - a) * v0 + a * v1
        return out

    def _apply_by_path(self, path: str, value: float) -> None:
        obj_name, field = path.split(".", 1)  # "eyes.dx"
        obj = getattr(self.state, obj_name)
        setattr(obj, field, value)

    def tick(self) -> FaceState:
        now = time.time()
        updates: dict[str, list[tuple[int, float]]] = {}
        kill = []
        for ch, layer in list(self._layers.items()):
            spec: GestureSpec = layer["spec"]
            t0 = layer["t0"]
            prio = layer["prio"]
            t = now - t0
            dur = spec.frames[-1].t if spec.frames else 0.0

            # wagi fade-in/out
            w_in = min(1.0, t / max(1e-6, spec.fade_in))
            w_out = 1.0 if t <= dur else max(0.0, 1.0 - (t - dur) / max(1e-6, spec.fade_out))
            w = _ease(min(w_in, w_out))

            if w <= 0.0 and t > dur + spec.fade_out:
                kill.append(ch)
                continue

            params = self._params_at(spec, min(t, dur))
            for path, v in params.items():
                updates.setdefault(path, []).append((prio, w * float(v)))

        for ch in kill:
            self._layers.pop(ch, None)

        # miks wg prio (przy remisie średnia)
        for path, lst in updates.items():
            best = max(lst, key=lambda p: p[0])[0]
            vals = [v for p, v in lst if p == best]
            self._apply_by_path(path, sum(vals) / max(1, len(vals)))

        return self.state
