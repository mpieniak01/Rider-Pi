"""Shared face behaviour: bounded intents, monotonic time and real audio levels."""

from __future__ import annotations

import os
import random
import time

from .animator import Animator
from .catalog import CATALOG, MOODS
from .gestures import GESTURES
from .renderer import FaceRenderer
from .schema import prepare


class FaceController:
    def __init__(
        self, size=240, fps=12, idle=True, *, clock=None, rng=None, style="legacy", power_mode="cable", catalog=None
    ):
        self.size, self.fps = size, fps
        self.clock = clock or time.monotonic
        self.rng = rng or random.Random()
        self.catalog = catalog or CATALOG
        self.renderer = FaceRenderer({}, size=size, style=style)
        self.anim = Animator(clock=self.clock)
        env_idle = os.getenv("FACE_IDLE_ENABLE")
        self.idle = (env_idle.lower() not in {"0", "false", "no"}) if env_idle is not None else idle
        self.power_mode = power_mode
        self.intensity, self.tempo, self.transition = 1.0, 1.0, "original"
        self.active_gestures = None
        self._speaking = False
        self._audio_at, self._audio_level = float("-inf"), 0.0
        self._next_blink = self.clock() + self._delay("FACE_IDLE_BLINK_SEC", 3)
        self._next_look = self.clock() + self._delay("FACE_IDLE_LOOK_SEC", 6)
        self._mood_current = "neutral"

    def _delay(self, key, default):
        base = float(os.getenv(key, str(default)))
        if base <= 0:
            return float("inf")
        jitter = max(0, float(os.getenv("FACE_IDLE_JITTER", "0.15")))
        return max(base * 0.6, base * self.rng.uniform(1 - jitter, 1 + jitter))

    def configure(self, settings):
        self.renderer.style = settings["style"]
        self.power_mode, self.idle = settings["power_mode"], settings["idle"]
        self.intensity, self.tempo, self.transition = settings["intensity"], settings["tempo"], settings["transition"]
        self.active_gestures = set(settings["active_gestures"])

    def set_expr(self, expr):
        if expr == "blink":
            return self.do("blink")
        self.set_mood(expr)

    def set_mood(self, target, via_neutral=True, dwell_s=None):
        if target not in MOODS:
            return
        if self.anim.state.mouth.curve is None:
            self.anim.state.mouth.curve = self.anim.value("mouth.curve")
        self.anim.state.expr = target
        self.anim.state.mouth.shape = target if target in {"neutral", "happy", "sad"} else "neutral"
        from .schema import FIELDS

        values = dict.fromkeys(FIELDS, 0.0)
        values.update(MOODS[target])
        values = {key: value * self.intensity for key, value in values.items()}
        if self.renderer.style == "legacy":
            values.pop("mouth.curve", None)
        duration = max(0.05, min(1.0, float(os.getenv("FACE_TRANS_STEP_S", "0.35"))))
        self.anim.start({"duration": duration, "initial": values}, prio=5, owner="emotion")
        self._mood_current = target

    def is_mood_idle(self):
        return "emotion" not in self.anim.owners.values()

    def do(self, name, *, priority=10, owner="gesture", intensity=None, tempo=None, transition=None, **kwargs):
        procedural = name in GESTURES
        if name in GESTURES and kwargs:
            if name == "look":
                kwargs["rng"] = self.rng
            spec = GESTURES[name](**kwargs)
        elif name == "look":
            spec = GESTURES[name](rng=self.rng)
        elif name in GESTURES:
            spec = GESTURES[name]()
        else:
            item = self.catalog.get(name)
            if not item or self.active_gestures is not None and item["id"] not in self.active_gestures:
                return False
            spec = item
            procedural = item["builtin"] and item["name"] in GESTURES
        if self.active_gestures is not None and name in GESTURES and "builtin:" + name not in self.active_gestures:
            return False
        spec = prepare(
            spec,
            self.intensity if intensity is None else intensity,
            self.tempo if tempo is None else tempo,
            self.transition if transition is None else transition,
            defaults=not procedural,
        )
        if owner == "idle":
            self.anim.tick()
            for path, segments in spec["tracks"].items():
                if segments:
                    segments[-1]["v1"] = self.anim.value(path)
        if not procedural:
            self.anim.state.expr = spec["expr"]
            self.anim.state.mouth.shape = spec["expr"] if spec["expr"] in {"neutral", "happy", "sad"} else "neutral"
        self.anim.start(spec, prio=priority, mode="blend", owner=owner)
        return True

    def speak(self, on=True):
        self._speaking = bool(on)
        if not on:
            self.audio_envelope(0, playing=False)

    def audio_envelope(self, level, *, playing=True):
        from .schema import number

        self._audio_level = number(level, 0, 1) if playing else 0.0
        self._speaking, self._audio_at = bool(playing), self.clock()
        self._mouth_to(self._audio_level)

    def _mouth_to(self, level):
        current = self.anim.value("mouth.open")
        duration = 0.08 if level > current else 0.14
        self.anim.start(
            {
                "duration": max(duration, 0.30),
                "tracks": {"mouth.open": [{"t0": 0, "t1": duration, "v0": current, "v1": level, "ease": "in_out"}]},
            },
            prio=100,
            owner="audio",
        )

    def _tick(self):
        now = self.clock()
        if self._speaking and now - self._audio_at > 0.25:
            self._speaking = False
            self._mouth_to(0)
        if self.idle:
            scale = 2.5 if self.power_mode == "battery" else 1.0
            if now >= self._next_blink:
                self.do("blink", priority=1, owner="idle")
                self._next_blink = now + self._delay("FACE_IDLE_BLINK_SEC", 3) * scale
                if self.rng.random() < float(os.getenv("FACE_BLINK_SHIFT_PROB", "0.12")):
                    self.do("look", priority=1, owner="idle")
            if now >= self._next_look:
                self.do("look", priority=1, owner="idle")
                self._next_look = now + self._delay("FACE_IDLE_LOOK_SEC", 6) * scale
        state = self.anim.tick()
        state.render_time = now
        override = os.getenv("FACE_MOUTH_SHAPE", "").lower()
        if override in {"happy", "neutral", "sad"}:
            state.mouth.shape = override
        if os.getenv("FACE_MOUTH_OPEN", ""):
            state.mouth.open = max(0, min(1, float(os.environ["FACE_MOUTH_OPEN"])))
        state.assist_speaking = self._speaking
        return state

    def frame_image(self):
        return self.renderer.render_image(self._tick())

    def frame(self):
        return self.renderer.render_png_bytes(self._tick())

    def loop(self, secs):
        deadline = self.clock() + float(secs)
        while self.clock() < deadline:
            started = self.clock()
            yield self.frame()
            time.sleep(max(0, 1 / max(1, self.fps) - (self.clock() - started)))

    def close(self):
        self.anim.cancel()
        self._speaking = False
