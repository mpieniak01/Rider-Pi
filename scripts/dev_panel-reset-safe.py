#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import inspect
import os
import pathlib
import pkgutil
import sys
import time


def iter_xgo_modules():
    mods = []
    xgo = importlib.import_module("xgoscreen")
    mods.append(xgo)
    if hasattr(xgo, "__path__"):
        for _, name, _ in pkgutil.walk_packages(xgo.__path__, xgo.__name__ + "."):
            try:
                mods.append(importlib.import_module(name))
            except Exception:
                pass
    for extra in ("xgoscreen.lcdconfig", "xgoscreen.lcd", "xgoscreen.screen"):
        try:
            m = importlib.import_module(extra)
            if m not in mods:
                mods.append(m)
        except Exception:
            pass
    return mods


def pick_device_class():
    cands = []
    for m in iter_xgo_modules():
        for n, o in vars(m).items():
            if inspect.isclass(o) and o.__module__ == m.__name__:
                has_show = any(
                    callable(getattr(o, a, None))
                    for a in (
                        "ShowImage",
                        "show_image",
                        "display",
                        "blit",
                        "put",
                        "present",
                    )
                )
                has_raw = all(hasattr(o, a) for a in ("SetWindows", "command", "spi_writebyte"))
                name_ok = any(k in n.lower() for k in ("lcd", "st77", "st7789", "display", "panel"))
                if has_show or has_raw or name_ok:
                    cands.append((n, o))
    if not cands:
        raise RuntimeError("Nie znalazłem klasy urządzenia w xgoscreen.*")
    cands.sort(
        key=lambda kv: (
            0 if "2inch" in kv[0].lower() else 1,
            0 if "lcd" in kv[0].lower() else 1,
            kv[0].lower(),
        )
    )
    return cands[0][1]


def chunk_write(dev, data: bytes, size: int = 2048):
    for i in range(0, len(data), size):
        dev.spi_writebyte(data[i : i + size])


def cmd(dev, c, data: bytes = b"", pause: float = 0.0):
    dev.command(c)
    if data:
        chunk_write(dev, data)
    if pause > 0:
        time.sleep(pause)


def be16(x):
    return bytes([(x >> 8) & 0xFF, x & 0xFF])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--madctl", default="0x68", help="MADCTL (orientacja) np. 0x68/0x60")
    ap.add_argument("--colmod", default="0x55", help="COLMOD (0x55 = RGB565)")
    ap.add_argument("--invert", choices=["on", "off"], default="off")
    ap.add_argument("--spi-hz", type=int, default=int(os.getenv("FACE_LCD_SPI_HZ", "0") or 0))
    ap.add_argument("--bars", action="store_true", help="Po resecie narysuj 4 pasy (R,G,B,White)")
    args = ap.parse_args()

    # ścieżki robocze
    ROOT = pathlib.Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(ROOT)]
    for p in os.getenv("RIDER_APPS_PATH", "apps").split(":"):
        p = p.strip()
        if p:
            cand = (ROOT / p).resolve()
            if cand.exists():
                sys.path.insert(0, str(cand))

    Dev = pick_device_class()
    try:
        dev = Dev()
    except TypeError:
        dev = Dev

    # ustaw SPI hz, jeśli jest
    try:
        if args.spi_hz and hasattr(dev, "SPI"):
            dev.SPI.max_speed_hz = args.spi_hz
    except Exception:
        pass

    # łagodny begin/init
    for name in ("begin", "Begin", "Init", "init"):
        fn = getattr(dev, name, None)
        if callable(fn):
            try:
                fn()
                break
            except Exception:
                pass

    # --- ST7789 „safe init” 240x320 ---
    # OFF, SLEEP IN, SWRESET
    cmd(dev, 0x28, pause=0.01)
    cmd(dev, 0x10, pause=0.01)
    cmd(dev, 0x01, pause=0.12)

    # SLEEP OUT
    cmd(dev, 0x11, pause=0.12)

    # COLMOD: 16bpp
    cmd(dev, 0x3A, bytes([int(str(args.colmod), 0)]), pause=0.01)

    # Porches / sterowanie (z typowych configów ST7789)
    cmd(dev, 0xB2, b"\x0c\x0c\x00\x33\x33")
    cmd(dev, 0xB7, b"\x35")
    cmd(dev, 0xBB, b"\x19")
    cmd(dev, 0xC0, b"\x2c")
    cmd(dev, 0xC2, b"\x01\xff")
    cmd(dev, 0xC3, b"\x12")
    cmd(dev, 0xC4, b"\x20")
    cmd(dev, 0xC6, b"\x0f")  # 60Hz
    cmd(dev, 0xD0, b"\xa4\xa1")

    # Gamma (łagodne, „bezpieczne”)
    cmd(dev, 0xE0, b"\xd0\x04\x0d\x11\x13\x2b\x3f\x54\x4c\x18\x0d\x0b\x1f\x23")
    cmd(dev, 0xE1, b"\xd0\x04\x0c\x11\x13\x2c\x3f\x44\x51\x2f\x1f\x1f\x20\x23")

    # MADCTL (orientacja)
    cmd(dev, 0x36, bytes([int(str(args.madctl), 0)]), pause=0.01)

    # Jawne okno adresowania 240x320 (X: 0..239, Y: 0..319)
    cmd(dev, 0x2A, be16(0) + be16(239))
    cmd(dev, 0x2B, be16(0) + be16(319))

    # Inversion
    cmd(dev, 0x21 if args.invert == "on" else 0x20, pause=0.01)

    # Display ON
    cmd(dev, 0x29, pause=0.05)

    spi_now = 0
    try:
        spi_now = getattr(getattr(dev, "SPI", None), "max_speed_hz", 0) or 0
    except Exception:
        pass
    print(
        f"Panel reinitialized (COLMOD=0x{int(str(args.colmod), 0):02X}, "
        f"MADCTL=0x{int(str(args.madctl), 0):02X}, invert={args.invert}, SPI={spi_now or args.spi_hz})."
    )

    if args.bars:
        # 4 poziome pasy: RED, GREEN, BLUE, WHITE
        w = getattr(dev, "width", 240) if isinstance(getattr(dev, "width", None), int) else 240
        h = getattr(dev, "height", 320) if isinstance(getattr(dev, "height", None), int) else 320

        def fill565(color565):
            cmd(dev, 0x2C)  # Memory Write
            line = color565 * (w)  # jedna linia
            for _ in range(h):
                chunk_write(dev, line)

        colors = [
            (0xF800, "RED"),
            (0x07E0, "GREEN"),
            (0x001F, "BLUE"),
            (0xFFFF, "WHITE"),
        ]
        for val, name in colors:
            print("bar:", name)
            hi, lo = (val >> 8) & 0xFF, val & 0xFF
            fill565(bytes([hi, lo]))
            time.sleep(0.4)
