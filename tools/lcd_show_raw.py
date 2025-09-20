#!/usr/bin/env python3
from __future__ import annotations
import importlib
import os
import sys
import time

from PIL import Image, ImageDraw

# ENV: FACE_LCD_SPI_HZ, FACE_SPI_MODE, FACE_MADCTL, FACE_COLMOD
SPI_HZ = int(os.getenv("FACE_LCD_SPI_HZ", "0") or 0)
SPI_MODE = int(os.getenv("FACE_SPI_MODE", "0") or 0)
MADCTL = int(os.getenv("FACE_MADCTL", "0x68"), 16)  # MX|MV|BGR – u Ciebie działało
COLMOD = int(os.getenv("FACE_COLMOD", "0x55"), 16)  # 16bpp

sys.path[:0] = ["/home/pi/robot", "/home/pi/robot/apps"]
fr = importlib.import_module("apps.ui.face_renderers")
lcd = fr.LCDRenderer(fr.FaceConfig(lcd_do_init=True, lcd_rotate=0, lcd_spi_hz=SPI_HZ))
d = lcd.device
W, H = lcd.width, lcd.height

# ustaw SPI mode jeśli mamy uchwyt
spi = getattr(d, "SPI", None)
if spi is not None and hasattr(spi, "mode"):
    try:
        spi.mode = SPI_MODE
    except Exception:
        pass


def wr(cmd, data=b"", dt=0.0, chunk=4096):
    d.command(cmd)
    if data:
        for i in range(0, len(data), chunk):
            d.spi_writebyte(data[i : i + chunk])
    if dt:
        time.sleep(dt)


# twardy, przewidywalny init
wr(0x28, dt=0.01)  # DISPOFF
wr(0x10, dt=0.01)  # SLPIN
wr(0x01, dt=0.12)  # SWRESET
wr(0x11, dt=0.12)  # SLPOUT
wr(0x3A, bytes([COLMOD]), 0.01)  # COLMOD
wr(0x36, bytes([MADCTL]), 0.01)  # MADCTL
wr(0x29, dt=0.05)  # DISPON

# obraz wejściowy albo testcard
src = None
if len(sys.argv) > 1:
    p = sys.argv[1]
    if os.path.exists(p):
        src = Image.open(p).convert("RGB")
if src is None:
    # testcard
    src = Image.new("RGB", (W, H))
    dr = ImageDraw.Draw(src)
    for i, c in enumerate(
        [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255), (255, 255, 255), (0, 0, 0)]
    ):
        dr.rectangle([0, i * H // 8, W, (i + 1) * H // 8 - 1], fill=c)
    dr.text((5, 5), "RAW TEST", fill=(0, 0, 0))

# ewentualna soft-rotacja 270° (jak Twoja buźka)
if os.getenv("ROTATE_270") == "1":
    src = src.rotate(270, expand=True)

src = src.resize((W, H), Image.BILINEAR)

# RGB888 -> RGB565 BE
px = src.tobytes()
buf = bytearray(W * H * 2)
di = 0
for i in range(0, len(px), 3):
    r, g, b = px[i], px[i + 1], px[i + 2]
    v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    buf[di] = (v >> 8) & 0xFF
    buf[di + 1] = v & 0xFF
    di += 2

# rysuj
d.SetWindows(0, 0, W - 1, H - 1)
wr(0x2C, buf)
print(f"[ok] RAW image pushed: {W}x{H}, SPI_HZ={SPI_HZ}, MODE={SPI_MODE}, MADCTL=0x{MADCTL:02X}, COLMOD=0x{COLMOD:02X}")
time.sleep(0.1)
