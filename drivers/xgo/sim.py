#!/usr/bin/env python3
"""
drivers/xgo/sim.py — Simulated XGO robot adapter

Provides a software simulator for the XGO robot, compatible with XgoAdapter interface.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

LOG = logging.getLogger("drivers.xgo.sim")


class SimulatedXgoAdapter:
    """
    Simulated XGO robot adapter for testing and development without hardware.

    This class provides the same interface as XgoAdapter but logs actions
    instead of controlling physical hardware.
    """

    def __init__(self, port: str = "/dev/null", version: str = "sim"):
        self._port = port
        self._version = version
        self._moving = False
        self._height = 0
        self._stabilization = False
        self._balance = False
        LOG.info(f"[SIM] XGO adapter initialized (port={port}, version={version})")

    def ok(self) -> bool:
        """Simulator is always available."""
        return True

    def available_methods(self) -> list[str]:
        """Return list of available methods."""
        return [
            "stop",
            "set_stabilization",
            "enable_balance",
            "set_height",
            "drive",
            "spin",
            "action",
            "led",
            "battery",
            "imu",
        ]

    def stop(self):
        """Stop all motion."""
        if self._moving:
            LOG.info("[SIM] STOP")
            self._moving = False

    def set_stabilization(self, on: bool):
        """Set stabilization mode."""
        self._stabilization = on
        LOG.debug(f"[SIM] Stabilization: {'ON' if on else 'OFF'}")

    def enable_balance(self, on: bool):
        """Enable/disable IMU balance."""
        self._balance = on
        LOG.debug(f"[SIM] Balance: {'ON' if on else 'OFF'}")

    def set_height(self, h: int):
        """Set suspension height."""
        h = max(-30, min(55, h))
        self._height = h
        LOG.debug(f"[SIM] Height: {h}")

    def drive(self, dir: str, speed: float, dur: float | None = None, *, block: bool = False) -> None:
        """
        Simulate forward/backward motion.

        Args:
            dir: "forward" or "backward"
            speed: 0..1
            dur: Duration in seconds (optional)
            block: Whether to block until complete
        """
        if dir not in ("forward", "backward"):
            LOG.warning(f"[SIM] Invalid direction: {dir}")
            return

        speed = max(0.0, min(1.0, speed))
        dur_str = f"{dur:.2f}s" if dur is not None else "continuous"
        block_str = " (blocking)" if block else ""
        LOG.info(f"[SIM] drive {dir} speed={speed:.2f} dur={dur_str}{block_str}")
        self._moving = True

    def spin(
        self,
        dir: str,
        speed: float,
        dur: float | None = None,
        deg: float | None = None,
        *,
        block: bool = False,
    ) -> None:
        """
        Simulate rotation.

        Args:
            dir: "left" or "right"
            speed: 0..1
            dur: Duration in seconds (optional)
            deg: Degrees to rotate (optional)
            block: Whether to block until complete
        """
        if dir not in ("left", "right"):
            LOG.warning(f"[SIM] Invalid direction: {dir}")
            return

        speed = max(0.0, min(1.0, speed))
        parts = [f"[SIM] spin {dir} speed={speed:.2f}"]
        if deg is not None:
            parts.append(f"deg={deg:.1f}°")
        if dur is not None:
            parts.append(f"dur={dur:.2f}s")
        if block:
            parts.append("(blocking)")
        LOG.info(" ".join(parts))
        self._moving = True

    def action(self, name: str) -> None:
        """Execute action."""
        LOG.info(f"[SIM] action: {name}")

    def led(self, idx: int, rgb: tuple[int, int, int] | Iterable[int]):
        """Set LED color."""
        if not isinstance(rgb, tuple):
            rgb = tuple(rgb)
        LOG.debug(f"[SIM] LED[{idx}] = RGB{rgb}")

    def battery(self) -> float | None:
        """Return simulated battery level (always 0.85 = 85%)."""
        return 0.85

    def imu(self) -> dict | None:
        """Return simulated IMU data (always level)."""
        return {"roll": 0.0, "pitch": 0.0, "yaw": 0.0}
