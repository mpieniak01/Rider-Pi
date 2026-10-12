"""Release only this preview's SPI handle before switching off an unused LCD."""

from __future__ import annotations

import logging

LOG = logging.getLogger("camera.lcd")


def close_preview_lcd(module, *, power_off=None):
    if module is None:
        return None
    name = "disp" if hasattr(module, "disp") else "_LCD"
    display = getattr(module, name, None)
    if display is None:
        return None
    # Detach first: nested finally blocks must never repeat a power operation.
    setattr(module, name, None)
    if hasattr(module, "LCD_ok"):
        module.LCD_ok = False
    if callable(getattr(display, "close", None)):
        return display.close()
    try:
        spi = getattr(display, "SPI", None)
        if spi is not None:
            spi.close()
    except Exception as exc:
        LOG.warning("LCD handle close failed: %s", exc)
        return {"ok": False, "error": "lcd_handle_close_failed"}
    if power_off is None:
        from apps.ui.lcd_power import off_if_free

        power_off = off_if_free
    try:
        result = power_off()
    except Exception as exc:
        LOG.warning("LCD shutdown unconfirmed: %s", exc)
        return {"ok": False, "error": "lcd_shutdown_unconfirmed"}
    if result.get("ok"):
        LOG.warning("LCD switched off after camera preview stopped")
    else:
        LOG.warning("LCD power unchanged: %s", result.get("error"))
    return result
