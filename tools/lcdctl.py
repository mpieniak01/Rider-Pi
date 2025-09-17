#!/usr/bin/env python3
"""
Rider-Pi LCD controller (2" SPI TFT) — ON/OFF + panel sleep/wake.

Używa:
  • SPI komend do panelu (ST77xx/ILI9xx style):
      OFF: DISP_OFF (0x28) + SLP_IN (0x10)
      ON : SLP_OUT (0x11) + DISP_ON (0x29)
  • Podświetlenia przez pojedynczy GPIO (BL pin) z konfigurowalną polaryzacją.

Domyślne (dopasowane do Twojej konfiguracji):
  BL_PIN=13 (BCM), BL_AH=1 (active-high: ON=HIGH, OFF=LOW), DC=25, RST=27,
  SPI_DEV=/dev/spidev0.0, SPI_HZ=12000000, SPI_MODE=0
"""
import os, time, argparse
from typing import Optional

BL_PIN   = int(os.getenv("FACE_LCD_BL_PIN", "13"))
BL_AH    = int(os.getenv("FACE_LCD_BL_AH", "1"))          # 1: ON=HIGH, 0: ON=LOW
DC_PIN   = int(os.getenv("FACE_LCD_DC_PIN", "25"))
RST_PIN  = int(os.getenv("FACE_LCD_RST_PIN", "27"))
SPI_DEV  = os.getenv("FACE_LCD_SPI_DEV", "/dev/spidev0.0")
SPI_HZ   = int(os.getenv("FACE_LCD_SPI_HZ", "12000000"))
SPI_MODE = int(os.getenv("FACE_SPI_MODE", "0"))

try:
    import spidev
except Exception:
    spidev = None

try:
    import RPi.GPIO as GPIO
except Exception:
    GPIO = None

def _gpio_setup():
    if GPIO is None:
        raise RuntimeError("RPi.GPIO nie jest dostępne (zainstaluj python3-rpi.gpio).")
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    for pin in (BL_PIN, DC_PIN, RST_PIN):
        GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)

def _spi_open():
    if spidev is None:
        raise RuntimeError("spidev nie jest dostępne (zainstaluj python3-spidev).")
    bus, dev = (0, 0)
    if SPI_DEV.startswith("/dev/spidev"):
        try:
            bus, dev = map(int, SPI_DEV.replace("/dev/spidev","").split("."))
        except Exception:
            pass
    s = spidev.SpiDev()
    s.open(bus, dev)
    s.max_speed_hz = SPI_HZ
    s.mode = SPI_MODE
    return s

def _cmd(spi, val: int):
    GPIO.output(DC_PIN, GPIO.LOW)
    spi.writebytes([val & 0xFF])

def _data(spi, data: bytes):
    GPIO.output(DC_PIN, GPIO.HIGH)
    if not data: return
    spi.writebytes(list(data))

def _panel_reset(spi):
    GPIO.output(RST_PIN, GPIO.HIGH); time.sleep(0.01)
    GPIO.output(RST_PIN, GPIO.LOW);  time.sleep(0.02)
    GPIO.output(RST_PIN, GPIO.HIGH); time.sleep(0.12)

def _bl(on: bool):
    level = GPIO.HIGH if (on ^ (BL_AH == 0)) else GPIO.LOW
    GPIO.output(BL_PIN, level)

def do_on(spi):
    _cmd(spi, 0x11)  # SLP_OUT
    time.sleep(0.12)
    _cmd(spi, 0x29)  # DISP_ON
    _bl(True)

def do_off(spi):
    _cmd(spi, 0x28)  # DISP_OFF
    time.sleep(0.01)
    _cmd(spi, 0x10)  # SLP_IN
    _bl(False)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["on","off","sleep","wake","reset"], help="Akcja panelu")
    ap.add_argument("--bl-pin", type=int, default=BL_PIN)
    ap.add_argument("--bl-ah",  type=int, default=BL_AH)
    ap.add_argument("--dc",     type=int, default=DC_PIN)
    ap.add_argument("--rst",    type=int, default=RST_PIN)
    ap.add_argument("--spi",    default=SPI_DEV)
    ap.add_argument("--hz",     type=int, default=SPI_HZ)
    ap.add_argument("--mode",   type=int, default=SPI_MODE)
    args = ap.parse_args()

    global BL_PIN, BL_AH, DC_PIN, RST_PIN, SPI_DEV, SPI_HZ, SPI_MODE
    BL_PIN, BL_AH, DC_PIN, RST_PIN = args.bl_pin, args.bl_ah, args.dc, args.rst
    SPI_DEV, SPI_HZ, SPI_MODE = args.spi, args.hz, args.mode

    _gpio_setup()
    spi = _spi_open()
    try:
        if args.action == "reset":
            _panel_reset(spi); do_on(spi)
        elif args.action in ("on","wake"):
            do_on(spi)
        elif args.action in ("off","sleep"):
            do_off(spi)
        print(f"[lcdctl] {args.action.upper()} done (spi_ok={spidev is not None}, bl_ok={GPIO is not None})")
    finally:
        try: spi.close()
        except Exception: pass
        if GPIO:
            try: GPIO.cleanup([BL_PIN, DC_PIN, RST_PIN, DC_PIN])
            except Exception: pass

if __name__ == "__main__":
    main()
