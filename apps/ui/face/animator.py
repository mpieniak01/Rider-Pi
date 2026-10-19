"""Monotonic, bounded animation channels. New intent replaces the same channel."""

from __future__ import annotations

import copy
import math
import time
from dataclasses import dataclass

from .model import FaceState
from .schema import MAX_PLAYBACK_DURATION_S

PATHS = {"eyes.dx", "eyes.dy", "eyes.blink", "brows.lift", "brows.tilt", "mouth.open", "mouth.curve"}


def _ease(kind, t):
    if kind in ("in", "ease_in"):
        return t * t
    if kind in ("out", "ease_out"):
        return 1 - (1 - t) ** 2
    if kind in ("in_out", "ease_in_out"):
        return t * t * (3 - 2 * t)
    return t


@dataclass
class _Channel:
    segments: list
    started: float
    ends: float
    priority: int
    owner: str
    initial: float


class Animator:
    def __init__(self, clock=None):
        self._clock = clock or time.monotonic
        self.state = FaceState()
        self._channels = {}

    @property
    def busy(self):
        return bool(self._channels)

    @property
    def owners(self):
        return {path: channel.owner for path, channel in self._channels.items()}

    def value(self, path):
        node, field = path.split(".")
        value = getattr(getattr(self.state, node), field)
        if value is None and path == "mouth.curve":
            shape = self.state.expr if self.state.mouth.shape == "auto" else self.state.mouth.shape
            return {"happy": 0.75, "sad": -0.65}.get(shape, 0.15)
        return float(value)

    def _set(self, path, value):
        node, field = path.split(".")
        setattr(getattr(self.state, node), field, value)

    def start(self, spec, prio=10, mode="blend", owner="gesture"):
        if mode not in {"blend", "replace"}:
            raise ValueError("invalid_animation_mode")
        duration = float(spec.get("duration", 0.2))
        if not math.isfinite(duration) or not 0 < duration <= MAX_PLAYBACK_DURATION_S:
            raise ValueError("invalid_animation_duration")
        self.tick()
        now = self._clock()
        tracks = copy.deepcopy(spec.get("tracks", {}))
        initial = spec.get("initial", {})
        for path in set(tracks) | set(initial):
            self._start_channel(path, tracks, initial, duration, mode, now, prio, owner)

    def _start_channel(self, path, tracks, initial, duration, mode, now, prio, owner):
        if path not in PATHS:
            raise ValueError("invalid_animation_channel")
        previous = self._channels.get(path)
        if previous and previous.priority > prio:
            return
        if mode == "replace" and path in initial:
            self._set(path, float(initial[path]))
        current = self.value(path)
        segments = self._channel_segments(path, current, tracks.get(path, []), initial, duration, mode)
        if segments:
            self._channels[path] = _Channel(segments, now, now + duration, prio, owner, current)

    def _channel_segments(self, path, current, segments, initial, duration, mode):
        if not segments and path in initial:
            if mode == "replace":
                segments = [{"t0": 0, "t1": duration, "v0": current, "v1": current, "ease": "lin"}]
            else:
                segments = [
                    {
                        "t0": 0,
                        "t1": duration,
                        "v0": current,
                        "v1": float(initial[path]),
                        "ease": "in_out",
                    }
                ]
        elif segments and mode == "blend" and segments[0]["t0"] == 0:
            segments[0]["v0"] = current
        return segments

    def cancel(self, owner=None):
        self._channels = {
            path: item for path, item in self._channels.items() if owner is not None and item.owner != owner
        }

    def tick(self):
        now = self._clock()
        for path, channel in list(self._channels.items()):
            elapsed = max(0, now - channel.started)
            value = channel.initial
            for segment in channel.segments:
                if elapsed < segment["t0"]:
                    break
                if elapsed >= segment["t1"]:
                    value = segment["v1"]
                else:
                    k = (elapsed - segment["t0"]) / (segment["t1"] - segment["t0"])
                    value = segment["v0"] + (segment["v1"] - segment["v0"]) * _ease(segment.get("ease", "lin"), k)
                    break
            self._set(path, float(value))
            if now >= channel.ends:
                self._set(path, float(channel.segments[-1]["v1"]))
                del self._channels[path]
        return self.state
