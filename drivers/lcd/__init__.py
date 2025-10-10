"""
LCD Display Driver

Hardware driver for LCD display (ILI9xx-based panels).
"""

from __future__ import annotations

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
        except ImportError:
            raise RuntimeError("SPI driver not available")
    else:
        raise ValueError(f"Unknown driver kind: {kind}")


__all__ = ["Driver", "make_driver", "PanelCfg"]
