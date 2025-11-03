#!/usr/bin/env python3
"""
drivers/lcd/sim.py — Simulated LCD display driver

Provides a software simulator for LCD display, compatible with the driver interface.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

LOG = logging.getLogger("drivers.lcd.sim")


class SimulatedLCDDriver:
    """
    Simulated LCD driver for testing without hardware.

    Logs display operations and optionally saves frames to /tmp for inspection.
    """

    def __init__(self, cfg=None, save_frames: bool = True):
        """
        Initialize simulated LCD driver.

        Args:
            cfg: Panel configuration (optional)
            save_frames: Whether to save frames to /tmp (default: True)
        """
        self.cfg = cfg
        self.save_frames = save_frames
        self.out_base = Path("/tmp/lcd_sim")
        self.frame_count = 0

        if save_frames:
            self.out_base.parent.mkdir(parents=True, exist_ok=True)
            LOG.info(f"[SIM] LCD frames will be saved to {self.out_base}_*.png")
        else:
            LOG.info("[SIM] LCD driver initialized (frames not saved)")

    def push_png(self, img):
        """
        Simulate pushing a PNG image to the display.

        Args:
            img: PIL Image object
        """
        self.frame_count += 1
        size = img.size if hasattr(img, "size") else "unknown"
        LOG.debug(f"[SIM] push_png frame={self.frame_count} size={size}")

        if self.save_frames:
            try:
                path = f"{self.out_base}_{self.frame_count:04d}.png"
                img.save(path)
                self._write_meta({"mode": "png", "size": list(size), "frame": self.frame_count})
            except Exception as e:
                LOG.warning(f"[SIM] Failed to save frame: {e}")

    def push_rgb565(self, buf: bytes, w: int, h: int):
        """
        Simulate pushing RGB565 buffer to the display.

        Args:
            buf: Raw RGB565 bytes
            w: Width in pixels
            h: Height in pixels
        """
        self.frame_count += 1
        LOG.debug(f"[SIM] push_rgb565 frame={self.frame_count} size={w}x{h} bytes={len(buf)}")

        if self.save_frames:
            try:
                # Save raw RGB565 data
                path = f"{self.out_base}_{self.frame_count:04d}.rgb565"
                with open(path, "wb") as f:
                    f.write(buf)

                # Try to convert to PNG for visualization
                try:
                    import numpy as np
                    from PIL import Image

                    arr = np.frombuffer(buf, dtype=">u2").reshape((h, w))
                    r = ((arr >> 11) & 0x1F) << 3
                    g = ((arr >> 5) & 0x3F) << 2
                    b = (arr & 0x1F) << 3
                    rgb = np.stack([r, g, b], axis=-1).astype("uint8")
                    img = Image.fromarray(rgb, "RGB")
                    png_path = f"{self.out_base}_{self.frame_count:04d}.png"
                    img.save(png_path)
                except ImportError:
                    # numpy/PIL not available, skip PNG conversion
                    pass

                self._write_meta(
                    {
                        "mode": "rgb565",
                        "size": [w, h],
                        "len": len(buf),
                        "frame": self.frame_count,
                    }
                )
            except Exception as e:
                LOG.warning(f"[SIM] Failed to save frame: {e}")

    def _write_meta(self, extra: dict):
        """Write frame metadata to JSON file."""
        try:
            meta = {
                "ts": datetime.now().isoformat(),
                "panel": self.cfg.as_dict() if hasattr(self.cfg, "as_dict") else {},
            }
            meta.update(extra)
            path = f"{self.out_base}_{self.frame_count:04d}.meta.json"
            with open(path, "w") as f:
                json.dump(meta, f, indent=2)
        except Exception as e:
            LOG.debug(f"[SIM] Failed to write metadata: {e}")


class SimulatedLCDRenderer:
    """
    Simulated version of LCDRenderer for compatibility with existing code.

    This provides the same interface as driver_ili9xx.LCDRenderer but logs
    operations instead of driving real hardware.
    """

    width: int = 240
    height: int = 320

    def __init__(self, cfg=None):
        self.cfg = cfg
        self.driver = SimulatedLCDDriver(cfg)
        LOG.info(f"[SIM] LCDRenderer initialized (size={self.width}x{self.height})")

    def ShowImage(self, img):
        """Show an image on the simulated display."""
        self.driver.push_png(img)
