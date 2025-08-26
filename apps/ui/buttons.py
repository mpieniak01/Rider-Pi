#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apps/ui/buttons.py — 4 przyciski → BUS topic `ui.button`
Payload:
  {"id":"LEFT|RIGHT|OK|BACK","event":"down|up|long","ts":...}
ENV:
  BTN_LEFT=24 BTN_RIGHT=23 BTN_OK=17 BTN_BACK=22
  BUTTONS_SIM=0|1   # gdy 1 → sterowanie z klawiatury (l/r/enter/backspace)
  HOLD_S=1.0        # czas długiego przytrzymania
"""
import os, sys, time

PROJ_ROOT = "/home/pi/robot"
if PROJ_ROOT not in sys.path:
    sys.path.insert(0, PROJ_ROOT)

from common.bus import BusPub
PUB = BusPub()

def _pub(topic: str, payload: dict):
    """Wyślij przez BusPub niezależnie od nazwy metody (send/publish/pub)."""
    for m in ("send", "publish", "pub"):
        if hasattr(PUB, m):
            return getattr(PUB, m)(topic, payload)
    raise AttributeError("BusPub has no send/publish/pub method")

def _publish(btn_id:str, ev:str):
    _pub("ui.button", {"id":btn_id, "event":ev, "ts":time.time()})

def _pins():
    return (
        int(os.getenv("BTN_LEFT", "24")),
        int(os.getenv("BTN_RIGHT","23")),
        int(os.getenv("BTN_OK",   "17")),
        int(os.getenv("BTN_BACK", "22")),
    )

def _log(msg): print(time.strftime("[%H:%M:%S]"), msg, flush=True)

def main_gpio():
    try:
        from gpiozero import Button
    except Exception as e:
        _log(f"GPIO not available ({e}); fallback to simulation. Set BUTTONS_SIM=1 to silence.")
        return main_sim()

    LEFT, RIGHT, OK, BACK = _pins()
    HOLD = float(os.getenv("HOLD_S","1.0"))

    btns = {
        "LEFT":  Button(LEFT,  pull_up=True, bounce_time=0.02, hold_time=HOLD),
        "RIGHT": Button(RIGHT, pull_up=True, bounce_time=0.02, hold_time=HOLD),
        "OK":    Button(OK,    pull_up=True, bounce_time=0.02, hold_time=HOLD),
        "BACK":  Button(BACK,  pull_up=True, bounce_time=0.02, hold_time=HOLD),
    }

    for name, b in btns.items():
        b.when_pressed  = (lambda n=name: ( _publish(n,"down") ))
        b.when_released = (lambda n=name: ( _publish(n,"up") ))
        b.when_held     = (lambda n=name: ( _publish(n,"long") ))

    _log(f"Buttons ready (GPIO): L={LEFT} R={RIGHT} OK={OK} BACK={BACK} hold={HOLD}s")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

def main_sim():
    import termios, tty, select
    _log("Buttons SIM: ←(h/a), →(l/d), OK=(Enter/Space/e), BACK=(Backspace/b). "
         "WIELKIE litery = 'long' (H/A/L/D/E/B). Ctrl+C aby wyjść.")
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        # małe litery / zwykłe klawisze = klik (down→up)
        keymap_click = {
            '\x1b[D': "LEFT",   # strzałka ←
            '\x1b[C': "RIGHT",  # strzałka →
            '\r': "OK", '\n': "OK",  # Enter
            ' ': "OK",                # spacja
            'e': "OK",
            '\x7f': "BACK",     # backspace
            'h': "LEFT", 'a': "LEFT",
            'l': "RIGHT",'d': "RIGHT",
            'b': "BACK",
        }
        # WIELKIE litery = long
        keymap_long = {
            'H': "LEFT", 'A': "LEFT",
            'L': "RIGHT",'D': "RIGHT",
            'E': "OK",
            'B': "BACK",
        }
        while True:
            if select.select([sys.stdin], [], [], 0.05)[0]:
                ch = sys.stdin.read(1)
                # obsługa sekwencji ESC dla strzałek
                if ch == '\x1b' and select.select([sys.stdin], [], [], 0.001)[0]:
                    ch += sys.stdin.read(1)
                    if select.select([sys.stdin], [], [], 0.001)[0]:
                        ch += sys.stdin.read(1)

                # priorytet: long (WIELKIE)
                btn = keymap_long.get(ch)
                if btn:
                    _publish(btn, "down")
                    _publish(btn, "long")
                    _publish(btn, "up")
                    continue

                # zwykłe kliki
                btn = keymap_click.get(ch)
                if btn:
                    _publish(btn, "down")
                    _publish(btn, "up")
                    continue
                # inne klawisze ignorujemy
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


if __name__ == "__main__":
    if os.getenv("BUTTONS_SIM","0") == "1":
        main_sim()
    else:
        main_gpio()
