#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apps/motion/main.py — odbiór intent.motion i wykonanie akcji (na razie stubs)
Sub: intent.motion   {"action":"forward|back|left|right|stop|sit|stand", "speed":0.4, "duration":1.5}
Pub: tts.speak       {"text":"..."} (opcjonalnie)
"""

import os, sys, time
PROJ_ROOT = "/home/pi/robot"
if PROJ_ROOT not in sys.path:
    sys.path.insert(0, PROJ_ROOT)

# bezpieczne printy
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

from common.bus import BusPub, BusSub
PUB = BusPub()
SUB = BusSub("intent.motion")

# XGO (opcjonalnie dostępny)
try:
    from xgolib import XGO
    HAS_XGO = True
except Exception:
    XGO = None
    HAS_XGO = False

g_car = None

LED_IDLE   = [0,0,0]
LED_ACTIVE = [60,40,0]   # pomarańcz
LED_OK     = [0,80,0]    # zielony
LED_ERR    = [80,0,0]    # czerwony

def log(msg):
    try:
        print(time.strftime("[%H:%M:%S]"), msg, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((time.strftime("[%H:%M:%S] ")+str(msg)+"\n").encode("utf-8","replace"))
        sys.stdout.flush()

def led(color):
    global g_car
    if not g_car: return
    try:
        g_car.rider_led(1, color)
        g_car.rider_led(0, color)
    except Exception:
        pass

def init_xgo():
    global g_car
    if not HAS_XGO:
        log("Motion: XGO lib not present — praca w trybie stub.")
        return
    try:
        g_car = XGO("xgorider")
        log("Motion: XGO OK")
    except Exception as e:
        g_car = None
        log(f"Motion: XGO init failed: {e}")

def do_action(intent: dict):
    action = intent.get("action")
    speed  = float(intent.get("speed", 0.4))
    dur    = float(intent.get("duration", 1.0))
    log(f"Motion: action={action} speed={speed} dur={dur}")

    led(LED_ACTIVE)

    # TODO: tu wstawimy realne API XGO. Poniżej — same logi (bezpiecznie).
    #
    # Przykład docelowy (pseudokod — do urealnienia po poznaniu API):
    # if g_car:
    #     if action == "forward": g_car.move(vx=+speed, vy=0, wz=0, t=dur)
    #     elif action == "back":  g_car.move(vx=-speed, vy=0, wz=0, t=dur)
    #     elif action == "left":  g_car.turn(wz=+speed, t=dur)
    #     elif action == "right": g_car.turn(wz=-speed, t=dur)
    #     elif action == "stop":  g_car.stop()
    #     elif action == "sit":   g_car.pose("sit")
    #     elif action == "stand": g_car.pose("stand")

    time.sleep(min(max(dur, 0.2), 3.0))  # symulacja czasu ruchu
    led(LED_OK)

def main():
    init_xgo()
    log("Motion: start (sub intent.motion)")
    while True:
        topic, payload = SUB.recv(timeout_ms=500)
        if topic is None:
            continue
        try:
            do_action(payload or {})
        except KeyboardInterrupt:
            raise
        except Exception as e:
            led(LED_ERR)
            log(f"Motion: error: {e}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        led(LED_IDLE)
        log("Motion: bye")
