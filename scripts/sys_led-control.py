#!/usr/bin/env python3

import argparse
import errno
import glob
import os
import pathlib
import sys
import time

LED_CLASS = "/sys/class/leds"

# ──────────────────────────────────────────────────────────────────────────────
# Helpers


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _good(msg: str) -> None:
    print(msg)


def _p(path, *extra) -> pathlib.Path:
    return pathlib.Path(path, *extra)


def _eacces_hint(p: pathlib.Path) -> None:
    _err(f"[err] permission denied: {p}")
    _err("      spróbuj z sudo, np.:  sudo ./scripts/sys_led-control.py off")


def write_text(p: pathlib.Path, val: str) -> bool:
    """Zapisz do pliku sysfs, z ładnym komunikatem o EACCES."""
    try:
        with open(p, "w") as f:
            f.write(val)
        return True
    except OSError as e:
        if e.errno == errno.EACCES:
            _eacces_hint(p)
        else:
            _err(f"[err] cannot write {p}: {e}")
        return False
    except Exception as e:
        _err(f"[err] cannot write {p}: {e}")
        return False


def read_text(p: pathlib.Path) -> str:
    try:
        return p.read_text()
    except Exception:
        return ""


# ──────────────────────────────────────────────────────────────────────────────
# LED discovery


def list_leds() -> list[pathlib.Path]:
    return [pathlib.Path(p) for p in sorted(glob.glob(f"{LED_CLASS}/*"))]


def pick_led(prefer: str | None) -> tuple[pathlib.Path, pathlib.Path, str] | None:
    """
    Zwraca (brightness, trigger, nazwa_led).
    prefer – nazwa katalogu w /sys/class/leds (np. ACT, PWR, led0).
    """
    leds = list_leds()
    if not leds:
        return None

    if prefer:
        lower = prefer.lower()
        for led in leds:
            if led.name.lower() == lower:
                return (_p(led, "brightness"), _p(led, "trigger"), led.name)

    # ustal priorytet
    order = ["act", "pwr", "led0", "led1"]
    byname = {led.name.lower(): led for led in leds}
    for key in order:
        if key in byname:
            led = byname[key]
            return (_p(led, "brightness"), _p(led, "trigger"), led.name)

    # fallback: pierwszy z listy
    led = leds[0]
    return (_p(led, "brightness"), _p(led, "trigger"), led.name)


# ──────────────────────────────────────────────────────────────────────────────
# Core ops


def ensure_manual(trigger: pathlib.Path) -> None:
    """Ustaw trigger=none, żeby ręcznie sterować brightness."""
    if trigger.exists():
        t = read_text(trigger)
        if "none" not in t:
            write_text(trigger, "none")


def set_led(brightness: pathlib.Path, trigger: pathlib.Path, value: int) -> bool:
    ensure_manual(trigger)
    return write_text(brightness, "1" if value else "0")


def status(brightness: pathlib.Path, trigger: pathlib.Path, name: str) -> None:
    b = read_text(brightness).strip() if brightness.exists() else "?"
    t = read_text(trigger).strip() if trigger.exists() else "<no trigger>"
    _good(f"{name}: brightness={b}  trigger={t}  paths=({brightness}, {trigger})")


def blink_loop(
    brightness: pathlib.Path,
    trigger: pathlib.Path,
    hz: float = 2.0,
    on_ms: int | None = None,
    off_ms: int | None = None,
) -> None:
    if on_ms is None or off_ms is None:
        period = 1.0 / max(hz, 0.1)
        on = off = period / 2.0
    else:
        on = max(on_ms, 1) / 1000.0
        off = max(off_ms, 1) / 1000.0

    ensure_manual(trigger)
    try:
        while True:
            if not write_text(brightness, "1"):
                break
            time.sleep(on)
            if not write_text(brightness, "0"):
                break
            time.sleep(off)
    except KeyboardInterrupt:
        write_text(brightness, "0")


# ──────────────────────────────────────────────────────────────────────────────
# CLI


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Prosty sterownik LED w /sys/class/leds (ACT/PWR/led0/led1)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument(
        "--led",
        help="nazwa LED (katalog w /sys/class/leds), np. ACT, PWR, led0",
        default=os.getenv("LED_NAME"),
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="wypisz dostępne LED-y")
    sub.add_parser("on", help="włącz LED")
    sub.add_parser("off", help="wyłącz LED")

    sp = sub.add_parser("blink", help="migaj LED-em")
    sp.add_argument("--hz", type=float, default=2.0, help="częstotliwość, gdy nie podano on/off-ms")
    sp.add_argument("--on-ms", type=int, help="czas świecenia w ms")
    sp.add_argument("--off-ms", type=int, help="czas zgaszenia w ms")

    sub.add_parser("status", help="pokaż stan LED-a")
    return ap


def main() -> None:
    args = build_parser().parse_args()

    if args.cmd == "list":
        leds = list_leds()
        if not leds:
            _err(f"[warn] {LED_CLASS} jest puste – brak LED-ów do sterowania")
            sys.exit(0)
        for led in leds:
            b = _p(led, "brightness")
            t = _p(led, "trigger")
            _good(
                f"{led.name:>8}  brightness={read_text(b).strip() or '?':<3}  trigger={read_text(t).strip() or '<n/a>'}"
            )
        sys.exit(0)

    picked = pick_led(args.led)
    if not picked:
        _err(f"[warn] brak LED-ów w {LED_CLASS}")
        sys.exit(0)

    brightness, trigger, name = picked

    if not brightness.exists():
        _err(f"[warn] {brightness} nie istnieje; brak sterowania")
        sys.exit(0)

    if args.cmd == "on":
        ok = set_led(brightness, trigger, 1)
        sys.exit(0 if ok else 1)

    if args.cmd == "off":
        ok = set_led(brightness, trigger, 0)
        sys.exit(0 if ok else 1)

    if args.cmd == "blink":
        blink_loop(brightness, trigger, args.hz, args.on_ms, args.off_ms)
        sys.exit(0)

    if args.cmd == "status":
        status(brightness, trigger, name)
        sys.exit(0)


if __name__ == "__main__":
    main()
