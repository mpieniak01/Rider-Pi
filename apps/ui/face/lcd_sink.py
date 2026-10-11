"""Optional LCD sink. Opens hardware only after current ownership allows it."""

from __future__ import annotations

import os
import re
import sys
import time

from PIL import Image

from apps.ui.status_panel import ownership_permits

_CLOSED_SPI = None


def _owned_spi_address(snapshot):
    paths = {row.get("path") for row in snapshot.get("holders", []) if row.get("pid") == os.getpid()}
    addresses = [
        tuple(map(int, match.groups()))
        for path in paths
        if isinstance(path, str) and (match := re.fullmatch(r"/dev/spidev(\d+)\.(\d+)", path))
    ]
    return addresses[0] if len(addresses) == 1 else None


def _reopen_shared_spi():
    global _CLOSED_SPI
    if _CLOSED_SPI is None:
        return None
    spi, address = _CLOSED_SPI
    try:
        spi.open(*address)
    except Exception:
        spi.close()
        raise
    _CLOSED_SPI = None
    return spi


class LcdUnavailable(RuntimeError):
    pass


class LcdSink:
    def __init__(self, *, probe=None, factory=None, power_off=None, report=None, clock=time.monotonic):
        if probe is None:
            from services.api_core.resource_diag import inspect

            def probe():
                return inspect("lcd")

        self.probe, self.clock = probe, clock
        self.rotate = int(os.getenv("FACE_LCD_ROTATE", os.getenv("SPLASH_ROTATE", "270")))
        if self.rotate not in {0, 90, 180, 270}:
            raise LcdUnavailable("invalid_lcd_rotation")
        snapshot = self.probe()
        if snapshot.get("free") is not True or not ownership_permits(snapshot):
            raise LcdUnavailable("lcd_owned_or_unknown")
        if factory is None:
            from drivers.lcd.driver_ili9xx import FaceConfig, LCDRenderer

            def factory():
                return LCDRenderer(FaceConfig(lcd_bl_pin=0))

        reopened = _reopen_shared_spi()
        try:
            self.driver = factory()
        except Exception:
            if reopened is not None:
                reopened.close()
            raise
        # Vendor lcdconfig keeps SpiDev in a shared constructor default. Retain
        # only the address observed for our descriptor so a later start can
        # reopen that handle after a stop released ownership.
        self._spi_address = _owned_spi_address(self.probe())
        self.power_off = power_off
        self.report = report
        self._last_probe = self.clock()
        self._closed = False
        self._canvas = None

    def present(self, image):
        if self.clock() - self._last_probe >= 1:
            self._last_probe = self.clock()
            if not ownership_permits(self.probe()):
                raise LcdUnavailable("lcd_owner_changed")
        device = getattr(self.driver, "device", self.driver)
        width = int(getattr(device, "width", getattr(device, "W", 240)))
        height = int(getattr(device, "height", getattr(device, "H", 320)))
        logical = (height, width) if self.rotate in {90, 270} else (width, height)
        if self._canvas is None or self._canvas.size != logical:
            self._canvas = Image.new("RGB", logical, image.getpixel((0, 0)))
        self._canvas.paste(image.getpixel((0, 0)), (0, 0, *logical))
        self._canvas.paste(image, ((logical[0] - image.width) // 2, (logical[1] - image.height) // 2))
        submitted = self._canvas.rotate(self.rotate, expand=True) if self.rotate else self._canvas
        self.driver.ShowImage(submitted)
        if self.report:
            known = getattr(self.driver, "_bl_pin", None) is not None
            self.report(
                on=True if known else None,
                power_known=known,
                presenting=True,
                rot=self.rotate,
                frame={
                    "layout": "procedural_face",
                    "rot": self.rotate,
                    "width": width,
                    "height": height,
                    "confirmation": "frame_write_accepted",
                    "physical_validity": "unverified",
                },
            )

    def close(self):
        global _CLOSED_SPI
        if getattr(self, "_closed", False):
            return
        self._closed = True
        device = getattr(self.driver, "device", None)
        spi = getattr(device, "SPI", None)
        if spi is not None:
            spi.close()
            if self._spi_address is not None and callable(getattr(spi, "open", None)):
                _CLOSED_SPI = (spi, self._spi_address)
        module = sys.modules.get(type(self.driver).__module__)
        raw = getattr(module, "_RAWSPI", None)
        raw_spi = raw.get("spi") if isinstance(raw, dict) else None
        if raw_spi is not None and raw_spi is not spi:
            raw_spi.close()
            raw.update(spi=None, inited=False)
        if self.power_off is None:
            from apps.ui.lcd_power import off_if_free

            self.power_off = off_if_free
        result = self.power_off()
        if self.report and isinstance(result, dict) and result.get("ok") is True:
            self.report(on=False, power_known=True, presenting=False, rot=self.rotate)
        return result
