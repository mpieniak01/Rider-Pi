#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rider-Pi LCD controller (2" SPI TFT) — ON/OFF (+ status, optional no-spi mode)

Pozostaje kompatybilny:
  sudo python3 ops/lcdctl.py off
  sudo python3 ops/lcdctl.py on

Nowości:
  sudo python3 ops/lcdctl.py status       # szybka diagnostyka
  sudo NO_SPI=1 python3 ops/lcdctl.py off # tylko podświetlenie (bez komend SPI)
  sudo python3 ops/lcdctl.py off --no-spi # j.w.

Env/flags:
  --bl 0|BCM     (FACE_LCD_BL_PIN)
  --bl-ah 0|1    (FACE_LCD_BL_ACTIVE_HIGH)   1: ON=HIGH
  --dc  BCM      (DC_PIN)      | -1 aby pominąć
  --rst BCM      (RST_PIN)     | -1 aby pominąć
  --spi /dev/spidevX.Y (SPI_DEV)
  --hz  HZ       (SPI_HZ)
  --no-spi       (NO_SPI=1)    | nie wysyłaj komend SPI (BL only)

Domyślne wartości zgodne z Twoją płytką.
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
DEF_NO_SPI  = bool(int(os.getenv("NO_SPI", "0") or "0"))

# ------- gpio / spi primitives ----------------------------------------------
def _has_root() -> bool:
    try:
        return os.geteuid() == 0  # type: ignore[attr-defined]
    except Exception:
        # na dziwnych env bez geteuid – przyjmijmy, że nie mamy root
        return False

def _set_bl(bl_pin: int, active_high: int, on: bool) -> bool:
    """Ustaw podświetlenie. Zwraca True jeśli *prawdopodobnie* się udało."""
    if bl_pin < 0:
        print("[lcdctl] INFO: BL pin < 0 → pomijam sterowanie podświetleniem")
        return True
    ok = True
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
        ok = False
        print(f"[lcdctl] WARN: backlight GPIO control failed: {e}")
    return ok

def _spi_cmds(dc_pin: int, rst_pin: int, spi_dev: str, hz: int, cmds: list[int]) -> bool:
    """Wyślij proste komendy do panelu. Zwraca True jeśli poszło bez wyjątku."""
    if spi_dev.strip() == "" or spi_dev == "none":
        print("[lcdctl] INFO: SPI disabled by spi_dev")
        return True
    ok = True
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
        # parse /dev/spidevX.Y
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
            time.sleep(0.001)
        spi.close()
    except Exception as e:
        ok = False
        print(f"[lcdctl] WARN: SPI command sequence failed: {e}")
    return ok

# ------- actions -------------------------------------------------------------
def do_off(args) -> int:
    # 1) Panel sleep (chyba że --no-spi), 2) BL off
    spi_ok = True
    if not args.no_spi:
        spi_ok = _spi_cmds(args.dc, args.rst, args.spi, args.hz, [0x28, 0x10])  # DISP_OFF, SLP_IN
        time.sleep(0.12)
    bl_ok = _set_bl(args.bl, args.bl_ah, on=False)
    print("[lcdctl] OFF done (spi_ok=%s, bl_ok=%s)" % (spi_ok, bl_ok))
    return 0 if (spi_ok or args.no_spi) and bl_ok else 2

def do_on(args) -> int:
    # 1) BL on (by widzieć efekt), 2) panel wake (chyba że --no-spi)
    bl_ok = _set_bl(args.bl, args.bl_ah, on=True)
    spi_ok = True
    if not args.no_spi:
        spi_ok &= _spi_cmds(args.dc, args.rst, args.spi, args.hz, [0x11])  # SLP_OUT
        time.sleep(0.12)
        spi_ok &= _spi_cmds(args.dc, args.rst, args.spi, args.hz, [0x29])  # DISP_ON
        time.sleep(0.02)
    print("[lcdctl] ON done (spi_ok=%s, bl_ok=%s)" % (spi_ok, bl_ok))
    return 0 if (spi_ok or args.no_spi) and bl_ok else 2

def do_status(args) -> int:
    # Bardzo prosta diagnostyka: dostępność SPI i BL
    spi_present = os.path.exists(args.spi) and os.access(args.spi, os.R_OK | os.W_OK)
    print(f"[lcdctl] SPI: {args.spi} present={spi_present} hz={args.hz} no_spi={args.no_spi}")
    if args.bl >= 0:
        try:
            import RPi.GPIO as GPIO  # type: ignore
            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(args.bl, GPIO.OUT)
            # odczyt nie zawsze ma sens (pin OUT), ale pokażemy co trzymamy
            val = GPIO.input(args.bl)
            logical_on = (val == GPIO.HIGH) if args.bl_ah else (val == GPIO.LOW)
            print(f"[lcdctl] BL GPIO BCM{args.bl}: phys={'HIGH' if val else 'LOW'} active_high={args.bl_ah} → {'ON' if logical_on else 'OFF'}")
        except Exception as e:
            print(f"[lcdctl] WARN: cannot read BL GPIO state: {e}")
    else:
        print("[lcdctl] BL GPIO disabled (bl < 0)")
    return 0

# ------- cli -----------------------------------------------------------------
def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Rider-Pi 2\" LCD ON/OFF controller")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp):
        sp.add_argument("--bl", type=int, default=DEF_BL_PIN, help=f"BL GPIO (default {DEF_BL_PIN}, -1 to skip)")
        sp.add_argument("--bl-ah", dest="bl_ah", type=int, choices=(0,1), default=DEF_BL_AH, help=f"BL active-high? 1/0 (default {DEF_BL_AH})")
        sp.add_argument("--dc",  type=int, default=DEF_DC_PIN,  help=f"DC GPIO (default {DEF_DC_PIN}, -1 to skip)")
        sp.add_argument("--rst", type=int, default=DEF_RST_PIN, help=f"RST GPIO (default {DEF_RST_PIN}, -1 to skip)")
        sp.add_argument("--spi", type=str, default=DEF_SPI,     help=f"SPI device (default {DEF_SPI})")
        sp.add_argument("--hz",  type=int, default=DEF_HZ,      help=f"SPI speed (default {DEF_HZ})")
        sp.add_argument("--no-spi", action="store_true", default=DEF_NO_SPI, help="do not send SPI commands (BL only)")

    sp_off = sub.add_parser("off", help="turn LCD off (sleep + backlight off)")
    add_common(sp_off)
    sp_off.set_defaults(func=do_off)

    sp_on  = sub.add_parser("on",  help="turn LCD on (wake + backlight on)")
    add_common(sp_on)
    sp_on.set_defaults(func=do_on)

    sp_stat = sub.add_parser("status", help="diagnose current setup")
    add_common(sp_stat)
    sp_stat.set_defaults(func=do_status)

    return p.parse_args()

def main() -> int:
    args = _parse()

    if not _has_root():
        # Nie blokujemy — sysfs/GPIO bywa dostępne różnie, ale podpowiedzmy.
        print("[lcdctl] WARN: nie wyglądasz na root; jeśli GPIO/SPI nie zadziała, użyj sudo.", file=sys.stderr)

    try:
        rc = int(bool(args.func(args)))
        return 0 if rc == 0 else 1
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"[lcdctl] ERROR: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
