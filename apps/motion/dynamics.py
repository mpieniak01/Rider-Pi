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
    linear_rate: float = 1.0
    turn_rate: float = 2.0
    watchdog_s: float = 0.5
    max_dt_s: float = 0.1

    @classmethod
    def from_env(cls):
        return cls(
            speed_limit=_env("MOTION_SPEED_LIMIT", 0.6),
            linear_rate=_env("MOTION_RAMP_LX", 1.0),
            turn_rate=_env("MOTION_RAMP_AZ", 2.0),
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
            "physical_calibration": "unverified",
            "yaw_convention": "negative_left_positive_right",
            "stop_bypasses_ramp": True,
        }


def approach(current, target, rate, dt):
    # Reach exactly zero before writing the opposite direction. A single tick
    # cannot jump across zero when a newer command asks for a reversal.
    if current * target < 0:
        target = 0.0
    delta = max(-rate * dt, min(rate * dt, target - current))
    return current + delta
