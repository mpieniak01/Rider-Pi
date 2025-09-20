#!/usr/bin/env python3
from __future__ import annotations
import importlib
import inspect
import os
import pkgutil
import struct
import sys
import time

# Parametry z ENV (łatwo zmieniać bez edycji pliku)
MADCTL = int(os.getenv("FACE_MADCTL", "0x68"), 16)  # 0x68 u Ciebie działało (MX|MV|BGR)
COLMOD = int(os.getenv("FACE_COLMOD", "0x55"), 16)  # 16bpp
SPIHZ = int(os.getenv("FACE_LCD_SPI_HZ", "24000000") or 0)  # konserwatywne 24 MHz
SPIMODE = int(os.getenv("FACE_SPI_MODE", "0"))  # spróbujemy 0 i 3
CHUNK = int(os.getenv("FACE_SPI_CHUNK", "2048"))

sys.path[:0] = ["/home/pi/robot", "/home/pi/robot/apps"]


def iter_xgo_modules():
    try:
        import xgoscreen
    except Exception as e:
        print("[diag] FATAL: brak xgoscreen:", e)
        sys.exit(2)
    mods = [xgoscreen]
    try:
        if hasattr(xgoscreen, "__path__"):
            for _, name, _ in pkgutil.walk_packages(xgoscreen.__path__, xgoscreen.__name__ + "."):
                try:
                    mods.append(importlib.import_module(name))
                except Exception:
                    pass
    except Exception:
        pass
    for extra in ("xgoscreen.lcdconfig", "xgoscreen.lcd", "xgoscreen.screen"):
        try:
            mods.append(importlib.import_module(extra))
        except Exception:
            pass
    # unikalne
    out = []
    for m in mods:
        if m not in out:
            out.append(m)
    return out


def pick_device_class():
    cands = []
    for m in iter_xgo_modules():
        for name, obj in vars(m).items():
            if inspect.isclass(obj) and obj.__module__ == m.__name__:
                any(
                    callable(getattr(obj, k, None))
                    for k in ("ShowImage", "show_image", "display", "blit", "put", "present")
                )
                has_raw = all(hasattr(obj, k) for k in ("SetWindows", "command", "spi_writebyte"))
                if has_raw:
                    cands.append((name, obj))
    if not cands:
        print("[diag] FATAL: brak klasy z SetWindows/command/spi_writebyte w xgoscreen.*")
        sys.exit(2)
    # preferuj nazwy z '2inch' lub 'lcd'
    cands.sort(key=lambda kv: (0 if "2inch" in kv[0].lower() else 1, 0 if "lcd" in kv[0].lower() else 1, kv[0].lower()))
    return cands[0][1]


def wr(dev, cmd, data=b"", dt=0.0):
    dev.command(cmd)
    if data:
        for i in range(0, len(data), CHUNK):
            dev.spi_writebyte(data[i : i + CHUNK])
    if dt:
        time.sleep(dt)


def u16be(x):
    return struct.pack(">H", x)


def main():
    # załaduj urządzenie
    Dev = pick_device_class()
    dev = Dev()
    # prędkość + tryb SPI (jeśli dostępne)
    spi = getattr(dev, "SPI", None)
    if spi is not None:
        try:
            if SPIHZ:
                spi.max_speed_hz = SPIHZ
            if hasattr(spi, "mode"):
                spi.mode = SPIMODE
            print(f"[diag] SPI set: hz={getattr(spi, 'max_speed_hz', None)} mode={getattr(spi, 'mode', None)}")
        except Exception as e:
            print("[diag] WARN spi params:", e)

    # podstawowe init (bez cudów)
    for name in ("begin", "Begin", "Init", "init"):
        fn = getattr(dev, name, None)
        if callable(fn):
            try:
                fn()
                break
            except Exception:
                pass

    # pełny soft reset/konfiguracja
    wr(dev, 0x28, dt=0.01)  # DISPOFF
    wr(dev, 0x10, dt=0.01)  # SLPIN
    wr(dev, 0x01, dt=0.12)  # SWRESET
    wr(dev, 0x11, dt=0.12)  # SLPOUT
    wr(dev, 0x3A, bytes([COLMOD]), 0.01)  # COLMOD=16bpp
    wr(dev, 0x36, bytes([MADCTL]), 0.01)  # MADCTL (orientacja/BGR)
    wr(dev, 0x29, dt=0.02)  # DISPON

    # wymiary
    W = getattr(dev, "width", None) or getattr(getattr(dev, "lcd", None), "width", None) or 240
    H = getattr(dev, "height", None) or getattr(getattr(dev, "lcd", None), "height", None) or 320
    print(f"[diag] Panel W={W} H={H}  MADCTL=0x{MADCTL:02X} COLMOD=0x{COLMOD:02X}")

    # pełne okno: CASET/RASET (ST7789)
    wr(dev, 0x2A, u16be(0) + u16be(W - 1))
    wr(dev, 0x2B, u16be(0) + u16be(H - 1))
    wr(dev, 0x2C)

    # trzy pełnoekranowe kolory (czerwony, zielony, niebieski)
    def fill565(val):
        line = (val.to_bytes(2, "big")) * W
        for y in range(H):
            dev.spi_writebyte(line)

    print("[diag] RED")
    fill565(0xF800)
    time.sleep(0.2)
    print("[diag] GREEN")
    fill565(0x07E0)
    time.sleep(0.2)
    print("[diag] BLUE")
    fill565(0x001F)
    time.sleep(0.2)
    print("[diag] DONE")


if __name__ == "__main__":
    main()
