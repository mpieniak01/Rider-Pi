#!/usr/bin/env python3
"""
Rider-Pi LCD controller (2" SPI TFT) — one file to turn the screen ON/OFF.

Only uses what we verified works on your setup:
  • SPI commands to the panel (ST77xx/ILI9xx style):
      OFF: DISP_OFF (0x28) + SLP_IN (0x10)
      ON : SLP_OUT (0x11) + DISP_ON (0x29)
  • Backlight via a single GPIO (BL pin) with configurable polarity.

Defaults match your board (discovered during tests):
  BL_PIN=0 (BCM0), BL_AH=1 (active-high: ON=HIGH, OFF=LOW), DC=25, RST=27,
  SPI_DEV=/dev/spidev0.0, SPI_HZ=12_000_000

Usage:
  sudo python3 scripts/lcdctl.py off            # sleep panel + backlight off
  sudo python3 scripts/lcdctl.py on             # wake panel + backlight on

Optional flags / environment overrides:
  --bl 0|BCM     (or env FACE_LCD_BL_PIN)
  --bl-ah 0|1    (or env FACE_LCD_BL_ACTIVE_HIGH)
  --dc  BCM      (or env DC_PIN)
  --rst BCM      (or env RST_PIN)
  --spi /dev/spidevX.Y   (or env SPI_DEV)
  --hz  HZ       (or env SPI_HZ)

Examples:
  sudo FACE_LCD_BL_PIN=0 FACE_LCD_BL_ACTIVE_HIGH=1 python3 scripts/lcdctl.py off
  sudo DC_PIN=25 RST_PIN=27 BL_PIN=0 BL_AH=1 SPI_DEV=/dev/spidev0.0 python3 scripts/lcdctl.py on
"""
from __future__ import annotations
import os, sys, time, argparse

# ------- helpers --------------------------------------------------------------
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default)

# Defaults discovered on your board
DEF_BL_PIN  = _env_int("FACE_LCD_BL_PIN", 0)
DEF_BL_AH   = _env_int("FACE_LCD_BL_ACTIVE_HIGH", 1)  # 1: ON=HIGH, OFF=LOW
DEF_DC_PIN  = _env_int("DC_PIN", 25)
DEF_RST_PIN = _env_int("RST_PIN", 27)
DEF_SPI     = _env_str("SPI_DEV", "/dev/spidev0.0")
DEF_HZ      = _env_int("SPI_HZ", 12_000_000)

# ------- gpio / spi primitives ----------------------------------------------

def _set_bl(bl_pin: int, active_high: int, on: bool) -> None:
    try:
        import RPi.GPIO as GPIO  # type: ignore
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(bl_pin, GPIO.OUT)
        if on:
            GPIO.output(bl_pin, GPIO.HIGH if active_high else GPIO.LOW)
        else:
            GPIO.output(bl_pin, GPIO.LOW if active_high else GPIO.HIGH)
        print(f"[lcdctl] BL GPIO BCM{bl_pin}: {'ON' if on else 'OFF'} (active_high={active_high})")
    except Exception as e:
        print(f"[lcdctl] WARN: backlight GPIO control failed: {e}")


def _spi_cmds(dc_pin: int, rst_pin: int, spi_dev: str, hz: int, cmds: list[int]) -> None:
    try:
        import spidev  # type: ignore
        import RPi.GPIO as GPIO  # type: ignore
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        if dc_pin >= 0:
            GPIO.setup(dc_pin, GPIO.OUT, initial=GPIO.LOW)
        if rst_pin >= 0:
            GPIO.setup(rst_pin, GPIO.OUT, initial=GPIO.HIGH)
            # Soft reset pulse keeps the bus sane
            GPIO.output(rst_pin, GPIO.LOW); time.sleep(0.01)
            GPIO.output(rst_pin, GPIO.HIGH); time.sleep(0.05)
        bus, dev = (0, 0)
        try:
            path = spi_dev.replace('/dev/spidev', '')
            bus, dev = [int(x) for x in path.split('.')]
        except Exception:
            pass
        spi = spidev.SpiDev()
        spi.open(bus, dev)
        spi.max_speed_hz = hz
        spi.mode = 0
        # send commands
        for c in cmds:
            if dc_pin >= 0:
                GPIO.output(dc_pin, GPIO.LOW)  # command
            spi.writebytes([c & 0xFF])
            # tiny guard
            time.sleep(0.001)
        spi.close()
    except Exception as e:
        print(f"[lcdctl] WARN: SPI command sequence failed: {e}")

# ------- actions -------------------------------------------------------------

def do_off(args) -> int:
    # 1) Put panel to sleep, then 2) disable backlight
    _spi_cmds(args.dc, args.rst, args.spi, args.hz, [0x28, 0x10])  # DISP_OFF, SLP_IN
    time.sleep(0.12)
    _set_bl(args.bl, args.bl_ah, on=False)
    print("[lcdctl] OFF done")
    return 0


def do_on(args) -> int:
    # 1) Enable backlight, then 2) wake the panel
    _set_bl(args.bl, args.bl_ah, on=True)
    _spi_cmds(args.dc, args.rst, args.spi, args.hz, [0x11])  # SLP_OUT
    time.sleep(0.12)
    _spi_cmds(args.dc, args.rst, args.spi, args.hz, [0x29])  # DISP_ON
    time.sleep(0.02)
    print("[lcdctl] ON done")
    return 0

# ------- cli -----------------------------------------------------------------

def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Rider-Pi 2\" LCD ON/OFF controller")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp):
        sp.add_argument("--bl", type=int, default=DEF_BL_PIN, help=f"BL GPIO (default {DEF_BL_PIN})")
        sp.add_argument("--bl-ah", dest="bl_ah", type=int, choices=(0,1), default=DEF_BL_AH, help=f"BL active-high? 1/0 (default {DEF_BL_AH})")
        sp.add_argument("--dc",  type=int, default=DEF_DC_PIN,  help=f"DC GPIO (default {DEF_DC_PIN})")
        sp.add_argument("--rst", type=int, default=DEF_RST_PIN, help=f"RST GPIO (default {DEF_RST_PIN})")
        sp.add_argument("--spi", type=str, default=DEF_SPI,     help=f"SPI device (default {DEF_SPI})")
        sp.add_argument("--hz",  type=int, default=DEF_HZ,      help=f"SPI speed (default {DEF_HZ})")

    sp_off = sub.add_parser("off", help="turn LCD off (sleep + backlight off)")
    add_common(sp_off)
    sp_off.set_defaults(func=do_off)

    sp_on  = sub.add_parser("on",  help="turn LCD on (wake + backlight on)")
    add_common(sp_on)
    sp_on.set_defaults(func=do_on)

    return p.parse_args()


def main() -> int:
    args = _parse()
    try:
        return int(bool(args.func(args)))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
