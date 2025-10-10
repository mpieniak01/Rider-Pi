#!/usr/bin/env python3
from __future__ import annotations

import importlib
import os
import sys
import time

# ENV (domyślne wartości to Twoje „pewne”):
MADCTL = int(os.getenv("MADCTL", "0x68"), 16)  # MX|MV|BGR
COLMOD = int(os.getenv("COLMOD", "0x55"), 16)  # 16bpp
SPIHZ = int(os.getenv("FACE_LCD_SPI_HZ", "0") or 0)
SPIMODE = int(os.getenv("FACE_SPI_MODE", "0") or 0)
INVERT = os.getenv("INVERT", "off").lower() in ("1", "on", "true", "yes")

sys.path[:0] = ["/home/pi/robot", "/home/pi/robot/apps"]
fr = importlib.import_module("apps.ui.face_renderers")
lcd = fr.LCDRenderer(fr.FaceConfig(lcd_do_init=True, lcd_rotate=0, lcd_spi_hz=SPIHZ))

# spróbuj ustawić SPI mode jeśli mamy uchwyt
spi = getattr(getattr(lcd, "device", None), "SPI", None)
if spi is not None and hasattr(spi, "mode"):
    try:
        spi.mode = SPIMODE
    except Exception:
        pass


# znajdź RAW (node z: command/spi_writebyte/SetWindows)
def get_raw(dev):
    for node in (
        dev,
        getattr(dev, "lcd", None),
        getattr(dev, "disp", None),
        getattr(dev, "display", None),
    ):
        if node and all(hasattr(node, m) for m in ("command", "spi_writebyte", "SetWindows")):
            return node
    raise RuntimeError("Brak RAW interfejsu (command/spi_writebyte/SetWindows)")


d = get_raw(lcd.device)


def wr(cmd, data=b"", dt=0.0, chunk=2048):
    d.command(cmd)
    if data:
        for i in range(0, len(data), chunk):
            d.spi_writebyte(data[i : i + chunk])
    if dt:
        time.sleep(dt)


# pełny, przewidywalny init + ustawienia
for cmd, dt in ((0x28, 0.01), (0x10, 0.01), (0x01, 0.12)):  # DISPOFF, SLPIN, SWRESET
    wr(cmd, dt=dt)
wr(0x11, dt=0.12)  # SLPOUT
wr(0x3A, bytes([COLMOD]), 0.01)  # COLMOD
wr(0x36, bytes([MADCTL]), 0.01)  # MADCTL
wr(0x20 if not INVERT else 0x21)  # invert OFF/ON
wr(0x29, dt=0.05)  # DISPON

# czyść ekran na czarno (nadpisz starą zawartość)
W = getattr(lcd, "width", 240)
H = getattr(lcd, "height", 320)
d.SetWindows(0, 0, W - 1, H - 1)
wr(0x2C)
black = b"\x00\x00" * (W * H)
for i in range(0, len(black), 2048):
    d.spi_writebyte(black[i : i + 2048])

print(
    print(
        f"... SPI={SPIHZ or getattr(spi, 'max_speed_hz', '-')} mode={getattr(spi, 'mode', '-')}",
    )
)
