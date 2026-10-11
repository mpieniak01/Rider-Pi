"""Normalized software ramp limits, not measured physical accelerations."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _env(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except (ValueError, OverflowError):
        return float("nan")


@dataclass(frozen=True)
class RampLimits:
    speed_limit: float = 0.6
    linear_rate: float = 3.0
    turn_rate: float = 4.0
    watchdog_s: float = 0.5
    max_dt_s: float = 0.1
    linear_deceleration: float = 3.0
    turn_deceleration: float = 4.0
    reversal_pause: float = 0.0
    ramp_mode: int = 0

    @classmethod
    def from_env(cls):
        return cls(
            speed_limit=_env("MOTION_SPEED_LIMIT", 0.6),
            linear_rate=_env("MOTION_RAMP_LX", 3.0),
            turn_rate=_env("MOTION_RAMP_AZ", 4.0),
            watchdog_s=_env("MOTION_WATCHDOG_MS", 500) / 1000.0,
        )

    @property
    def valid(self):
        values = (self.speed_limit, self.linear_rate, self.turn_rate, self.watchdog_s, self.max_dt_s)
        return (
            all(finite(value) for value in values)
            and 0 < self.speed_limit <= 1
            and all(value > 0 for value in values[1:])
            and self.watchdog_s <= 0.5
            and self.max_dt_s <= 0.1
            and finite(self.linear_deceleration)
            and self.linear_deceleration > 0
            and finite(self.turn_deceleration)
            and self.turn_deceleration > 0
            and finite(self.reversal_pause)
            and 0 <= self.reversal_pause <= 0.25
            and type(self.ramp_mode) is int
            and self.ramp_mode in (0, 1, 2)
        )

    def status(self):
        return {
            "ready": self.valid,
            "error": None if self.valid else "invalid_motion_limits",
            "units": "normalized_command_per_second",
            "linear_rate": self.linear_rate if finite(self.linear_rate) else None,
            "turn_rate": self.turn_rate if finite(self.turn_rate) else None,
            "speed_limit": self.speed_limit if finite(self.speed_limit) else None,
            "max_dt_s": self.max_dt_s,
            "linear_deceleration": self.linear_deceleration,
            "turn_deceleration": self.turn_deceleration,
            "reversal_pause": self.reversal_pause,
            "physical_calibration": "unverified",
            "yaw_convention": "negative_left_positive_right",
            "stop_bypasses_ramp": True,
            "ramp_mode": self.ramp_mode,
        }


def approach(current, target, rate, dt):
    # Reach exactly zero before writing the opposite direction. A single tick
    # cannot jump across zero when a newer command asks for a reversal.
    if current * target < 0:
        target = 0.0
    delta = max(-rate * dt, min(rate * dt, target - current))
    return current + delta


def curve_factor(mode):
    """Maximum slope of the normalized curve, so rate remains a ceiling."""
    return (1.0, 1.875, 4.0 / math.log(5.0))[mode]


def curve_fraction(mode, progress):
    x = max(0.0, min(1.0, progress))
    if mode == 1:
        return x * x * x * (10 + x * (-15 + 6 * x))
    if mode == 2:
        return math.log1p(4 * x) / math.log(5.0)
    return x


class CurveRamp:
    """Bounded command curves; unchanged hold renewals preserve progress.

    Goal changes replan from the current output. This is not a full physical
    jerk controller, and a changed goal can change the command slope.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.plan = None
        self.elapsed = 0.0
        self.origin = 0.0
        self.duration = 0.0

    def step(self, current, target, rate, dt, mode):
        if mode == 0:
            self.reset()
            return approach(current, target, rate, dt)
        if current * target < 0:
            target = 0.0
        plan = (target, rate, mode)
        if self.plan != plan:
            self.plan = plan
            self.origin = current
            self.elapsed = 0.0
            self.duration = abs(target - current) * curve_factor(mode) / rate
        if not self.duration:
            return target
        self.elapsed = min(self.duration, self.elapsed + dt)
        output = self.origin + (target - self.origin) * curve_fraction(mode, self.elapsed / self.duration)
        # Explicit rate ceiling also handles changes in clock / floating precision.
        result = approach(current, output, rate, dt)
        return result
