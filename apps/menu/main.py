#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apps/menu/main.py — proste menu na 4 przyciski (bez LCD)
Sub: ui.button, motion.state
Pub: system.mode, motion.cmd(stop), system.menu.state
"""
import os, sys, time

PROJ_ROOT = "/home/pi/robot"
if PROJ_ROOT not in sys.path:
    sys.path.insert(0, PROJ_ROOT)

from common.bus import BusPub, BusSub

PUB = BusPub()
SUB_BTN = BusSub("ui.button")
SUB_MS  = BusSub("motion.state")

HOME_ITEMS = ["Dema", "Autonomia", "Teleop", "Ustawienia", "Logi"]
LOW_BATTERY_LIMIT = 0.15

state = {
    "screen":"home",
    "cursor":0,
    "battery":None,
}

def pub(topic, payload):
    # kompatybilnie z różnymi implementacjami BusPub
    for m in ("send","publish","pub"):
        if hasattr(PUB, m): return getattr(PUB, m)(topic, payload)

def pub_stop():
    pub("motion.cmd", {"type":"stop"})

def pub_menu_state():
    pub("system.menu.state", {
        "screen": state["screen"],
        "cursor": state["cursor"],
        "items": HOME_ITEMS if state["screen"]=="home" else [],
        "ts": time.time(),
        "battery": state["battery"],
    })

def low_batt_blocked():
    b = state["battery"]
    return (b is not None) and (b < LOW_BATTERY_LIMIT)

def on_ok():
    if state["screen"] == "home":
        item = HOME_ITEMS[state["cursor"]]
        if item == "Dema":
            if low_batt_blocked(): return
            pub_stop()
            pub("system.mode", {"mode":"demos","demo":"trajectory","ts":time.time()})
        elif item == "Autonomia":
            if low_batt_blocked(): return
            pub_stop()
            pub("system.mode", {"mode":"autonomy","ts":time.time()})
        elif item == "Teleop":
            pub_stop()
            pub("system.mode", {"mode":"teleop","ts":time.time()})
        elif item == "Ustawienia":
            # placeholder – na razie nic nie robi
            pass
        elif item == "Logi":
            # np. przełącz poziom logów – placeholder
            pass

def on_back():
    # BACK jako szybki STOP
    pub_stop()

def on_left():
    if state["screen"] == "home":
        state["cursor"] = (state["cursor"] - 1) % len(HOME_ITEMS)

def on_right():
    if state["screen"] == "home":
        state["cursor"] = (state["cursor"] + 1) % len(HOME_ITEMS)

def log(msg): print(time.strftime("[%H:%M:%S]"), msg, flush=True)

def main():
    log("Menu: start (buttons + motion.state)")
    last_pub = 0
    try:
        while True:
            # buttons
            t, p = SUB_BTN.recv(timeout_ms=50)
            if t:
                btn = (p.get("id") or "").upper()
                ev  = (p.get("event") or "").lower()
                if ev == "down":
                    if   btn == "LEFT":  on_left()
                    elif btn == "RIGHT": on_right()
                    elif btn == "OK":    on_ok()
                    elif btn == "BACK":  on_back()
            # battery
            t2, p2 = SUB_MS.recv(timeout_ms=0)
            if t2:
                b = p2.get("battery")
                try:
                    state["battery"] = float(b) if b is not None else None
                except Exception:
                    pass
            # periodic menu state (dla debug/logów)
            if time.time() - last_pub > 1.0:
                last_pub = time.time()
                pub_menu_state()
    except KeyboardInterrupt:
        pass
    finally:
        log("Menu: bye")

if __name__ == "__main__":
    main()
