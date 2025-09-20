#!/usr/bin/env python3
from __future__ import annotations
import importlib
import os
import sys

from PIL import Image, ImageDraw

SPI_HZ = int(os.getenv("FACE_LCD_SPI_HZ", "0") or 0)
SPI_MODE = int(os.getenv("FACE_SPI_MODE", "0") or 0)

sys.path[:0] = ["/home/pi/robot", "/home/pi/robot/apps"]
xs = importlib.import_module("xgoscreen")


def find_dev():
    # 1) szukaj klasy z ShowImage tuż pod xgoscreen
    for name in dir(xs):
        obj = getattr(xs, name)
        if hasattr(obj, "ShowImage") and callable(getattr(obj, "ShowImage")):
            try:
                return obj()
            except Exception:
                pass
    # 2) szukaj w podmodułach
    import importlib
    import pkgutil

    for _, modname, _ in pkgutil.walk_packages(xs.__path__, xs.__name__ + "."):
        try:
            m = importlib.import_module(modname)
        except Exception:
            continue
        for name in dir(m):
            c = getattr(m, name)
            if getattr(c, "__name__", "").lower().find("lcd") >= 0 and hasattr(c, "ShowImage"):
                try:
                    return c()
                except Exception:
                    pass
    return None


dev = find_dev()
if dev is None:
    raise SystemExit("Nie znalazłem klasy z ShowImage w xgoscreen.*")

for meth in ("begin", "Begin", "Init", "init"):
    fn = getattr(dev, meth, None)
    if callable(fn):
        try:
            fn()
        except Exception:
            pass

spi = getattr(dev, "SPI", None)
if spi is not None:
    try:
        if SPI_HZ:
            spi.max_speed_hz = SPI_HZ
        if hasattr(spi, "mode"):
            spi.mode = SPI_MODE
    except Exception:
        pass

W = getattr(dev, "width", 240)
H = getattr(dev, "height", 320)
img = Image.new("RGB", (W, H), "white")
d = ImageDraw.Draw(img)

# Kolorowe pasy
colors = ["red", "green", "blue", "yellow", "magenta", "cyan", "orange"]
bw = max(1, W // len(colors))
for i, c in enumerate(colors):
    d.rectangle((i * bw, 0, (i + 1) * bw - 1, H), fill=c)

# Obwódka + przekątne
d.rectangle((0, 0, W - 1, H - 1), outline="black")
d.line((0, 0, W - 1, H - 1), fill="white", width=3)
d.line((0, H - 1, W - 1, 0), fill="white", width=3)

dev.ShowImage(img)
print(f"[presenter] testcard pushed, W={W} H={H}, hz={SPI_HZ} mode={SPI_MODE}")
