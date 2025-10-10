"""
LCD Display Driver

Hardware driver for LCD display (ILI9xx-based panels).
"""

from __future__ import annotations

import os
from typing import Literal

from .panel_cfg import PanelCfg


class Driver:
    """Base driver interface for LCD display."""

    def push_png(self, img):
        raise NotImplementedError

    def push_rgb565(self, buf: bytes, w: int, h: int):
        raise NotImplementedError


def make_driver(kind: Literal["mock", "spi"], cfg: PanelCfg) -> Driver:
    """
    Factory function to create LCD driver instances.

    Args:
        kind: Type of driver ("mock" or "spi")
        cfg: Panel configuration

    Returns:
        Driver instance
    """
    if kind == "mock":
        from .mock import MockFaceDriver

        return MockFaceDriver(cfg)
    elif kind == "spi":
        try:
            from .spi import SpiFaceDriver

            return SpiFaceDriver(cfg)
        except ImportError as err:
            raise RuntimeError("SPI driver not available") from err
    else:
        raise ValueError(f"Unknown driver kind: {kind}")


def get_lcd_driver(cfg: PanelCfg | None = None):
    """
    Factory function to get the appropriate LCD driver.

    Returns physical driver by default, or simulated driver if RIDER_SIMULATOR=1.

    Args:
        cfg: Panel configuration (optional, will use defaults if not provided)

    Returns:
        LCD driver instance (real or simulated)
    """
    if cfg is None:
        cfg = PanelCfg()

    if os.getenv("RIDER_SIMULATOR", "0") == "1":
        from .sim import SimulatedLCDRenderer

        return SimulatedLCDRenderer(cfg)
    else:
        # Try to import the real LCD renderer
        try:
            from .driver_ili9xx import LCDRenderer

            return LCDRenderer(cfg)
        except ImportError:
            # Fallback to mock if hardware not available
            from .mock import MockFaceDriver

            return MockFaceDriver(cfg)


__all__ = ["Driver", "make_driver", "PanelCfg", "get_lcd_driver"]
