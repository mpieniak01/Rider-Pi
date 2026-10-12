"""Optional camera display uses the same owner, wiring and cleanup as faces."""

from __future__ import annotations

from apps.ui.lcd_sink import LcdSink


def open_preview(*, disabled=False, no_draw=False):
    if disabled or no_draw:
        return None
    return LcdSink()
