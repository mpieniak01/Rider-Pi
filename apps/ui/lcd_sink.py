"""Shared LCD sink. Opens hardware only after current ownership allows it."""

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
        from drivers.lcd.board import lcd_board

        try:
            board = lcd_board()
        except ValueError as error:
            raise LcdUnavailable(str(error)) from error
        self.rotate = board.rotate
        if self.rotate not in {0, 90, 180, 270}:
            raise LcdUnavailable("invalid_lcd_rotation")
        snapshot = self.probe()
        if snapshot.get("free") is not True or not ownership_permits(snapshot):
            raise LcdUnavailable("lcd_owned_or_unknown")
        if factory is None:

            def factory():
                # Importing the vendor backend can open SPI. Delay even the
                # import until the lease and second ownership probe succeeded.
                from drivers.lcd.driver_ili9xx import FaceConfig, LCDRenderer

                return LCDRenderer(FaceConfig(lcd_bl_pin=board.bl, lcd_spi_hz=board.hz))

        from drivers.lcd.lease import LCDLease

        try:
            self._lease = LCDLease()
        except RuntimeError as error:
            raise LcdUnavailable(str(error)) from error
        reopened = None
        try:
            if self.probe().get("free") is not True:
                raise LcdUnavailable("lcd_owned_or_unknown")
            reopened = _reopen_shared_spi()
            self.driver = factory()
        except Exception:
            try:
                if reopened is not None:
                    reopened.close()
            finally:
                self._lease.close()
            raise
        # Vendor lcdconfig keeps SpiDev in a shared constructor default. Retain
        # only the address observed for our descriptor so a later start can
        # reopen that handle after a stop released ownership.
        try:
            self._spi_address = _owned_spi_address(self.probe())
        except BaseException:
            self._spi_address = None
            self.release()
            raise
        from services.core.lcd_state import invalidate

        invalidate()
        from services.core.resource_observation import invalidate as invalidate_owner

        invalidate_owner("lcd")
        self.power_off = power_off
        self.report = report
        self._last_probe = self.clock()
        self._closed = False
        self._canvas = None

    def present(self, image):
        device = getattr(self.driver, "device", self.driver)
        width = int(getattr(device, "width", getattr(device, "W", 240)))
        height = int(getattr(device, "height", getattr(device, "H", 320)))
        logical = (height, width) if self.rotate in {90, 270} else (width, height)
        if self._canvas is None or self._canvas.size != logical:
            self._canvas = Image.new("RGB", logical, image.getpixel((0, 0)))
        self._canvas.paste(image.getpixel((0, 0)), (0, 0, *logical))
        self._canvas.paste(image, ((logical[0] - image.width) // 2, (logical[1] - image.height) // 2))
        submitted = self._canvas.rotate(self.rotate, expand=True) if self.rotate else self._canvas
        self.present_device(submitted)
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

    def present_device(self, image):
        """Write already oriented boot/status pixels without a second rotation."""
        if self.clock() - self._last_probe >= 1:
            self._last_probe = self.clock()
            if not ownership_permits(self.probe()):
                raise LcdUnavailable("lcd_owner_changed")
        self.driver.ShowImage(image)

    def release(self):
        """Release owned handles; the guarded power operation is separate."""
        global _CLOSED_SPI
        if getattr(self, "_released", False):
            if getattr(self, "_release_error", None) is not None:
                raise self._release_error
            return
        errors = []
        device = getattr(self.driver, "device", None)
        spi = getattr(device, "SPI", None)
        module = sys.modules.get(type(self.driver).__module__)
        raw = getattr(module, "_RAWSPI", None)
        raw_spi = raw.get("spi") if isinstance(raw, dict) else None
        for handle in [spi, raw_spi if raw_spi is not spi else None]:
            if handle is None:
                continue
            try:
                handle.close()
                if handle is spi and self._spi_address is not None and callable(getattr(spi, "open", None)):
                    _CLOSED_SPI = (spi, self._spi_address)
                elif handle is raw_spi:
                    raw.update(spi=None, inited=False)
            except Exception as error:
                errors.append(error)
        self._lease.close()
        self._released = True
        from services.core.resource_observation import invalidate

        invalidate("lcd")
        if errors:
            self._release_error = RuntimeError("lcd_handle_close_failed")
            raise self._release_error from errors[0]

    def close(self):
        if self._closed:
            return getattr(self, "_close_result", None)
        self.release()
        if self.power_off is None:
            from apps.ui.lcd_power import off_if_free

            self.power_off = off_if_free
        result = self.power_off()
        self._close_result = result
        self._closed = True
        if self.report and isinstance(result, dict) and result.get("ok") is True:
            self.report(on=False, power_known=True, presenting=False, rot=self.rotate)
        return result
