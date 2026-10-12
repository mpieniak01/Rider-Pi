"""Finish LCD shutdown after systemd has released the producer descriptors."""

from __future__ import annotations


def finish_lcd_stop(unit, action, result, *, power_off=None):
    if action != "stop" or not result.get("ok") or unit != "lcd-renderer.service":
        return result
    if power_off is None:
        from apps.ui.lcd_power import off_if_free

        power_off = off_if_free
    try:
        power = power_off()
    except Exception as exc:
        power = {"ok": False, "error": "lcd_off_unconfirmed", "detail": str(exc)}
    result = {**result, "lcd_power": power}
    # A renderer STOP is an explicit request to turn off the panel, including
    # an already stopped renderer. A camera STOP may leave another LCD owner.
    if unit == "lcd-renderer.service" and not power.get("ok"):
        result.update(ok=False, error=power.get("error", "lcd_off_unconfirmed"))
    return result
