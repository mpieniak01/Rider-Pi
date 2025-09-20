#!/usr/bin/env python3
import importlib
import os
import struct
import sys
import time

MADCTL = int(os.getenv("MADCTL", "0x68"), 16)  # domyślnie MX|MV|BGR – u Ciebie działało
COLMOD = int(os.getenv("COLMOD", "0x55"), 16)  # 16 bpp
SPIHZ = int(os.getenv("FACE_LCD_SPI_HZ", "0") or 0)

sys.path[:0] = ["/home/pi/robot", "/home/pi/robot/apps"]
fr = importlib.import_module("apps.ui.face_renderers")
lcd = fr.LCDRenderer(fr.FaceConfig(lcd_do_init=True, lcd_rotate=0, lcd_spi_hz=SPIHZ))
d = lcd.device
W, H = lcd.width, lcd.height


def wr(cmd, data=b"", dt=0.0, chunk=2048):
    d.command(cmd)
    if data:
        for i in range(0, len(data), chunk):
            d.spi_writebyte(data[i : i + chunk])
    if dt:
        time.sleep(dt)


# pełny, przewidywalny init
wr(0x28, dt=0.02)  # DISPOFF
wr(0x10, dt=0.02)  # SLPIN
wr(0x01, dt=0.12)  # SWRESET
wr(0x11, dt=0.12)  # SLPOUT
wr(0x3A, bytes([COLMOD]), 0.01)  # COLMOD 16bpp
wr(0x36, bytes([MADCTL]), 0.01)  # MADCTL


# okno 0..W-1 / 0..H-1 (CASET/RASET)
def be16(x):
    return struct.pack(">H", x)


wr(0x2A, be16(0) + be16(W - 1))
wr(0x2B, be16(0) + be16(H - 1))
wr(0x29, dt=0.02)  # DISPON


# prosty wzorzec RGB pasów – potwierdza, że RAM zapisuje się w całości
def fill(color565):
    wr(0x2C)  # RAMWR
    line = color565 * W
    for _ in range(H):
        wr(0x3C, line)  # RAMWR continue (0x3C) – wiele sterów to lubi


def c565(r, g, b):
    v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    return bytes([(v >> 8) & 0xFF, v & 0xFF])


for col in (c565(255, 0, 0), c565(0, 255, 0), c565(0, 0, 255), c565(255, 255, 255), c565(0, 0, 0)):
    fill(col)
    time.sleep(0.25)

print(f"OK: init COLMOD=0x{COLMOD:02X}, MADCTL=0x{MADCTL:02X}, SPI={SPIHZ or 'driver default'}; W={W} H={H}")
