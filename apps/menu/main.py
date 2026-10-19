#!/usr/bin/env python3
from __future__ import annotations

"""
apps/menu/main.py — proste menu na 4 przyciski (bez LCD)
Sub: ui.button, motion.state
Pub: system.mode, motion.command(stop), system.menu.state
"""

import sys  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402

from apps.ui.status_panel import battery_observation  # noqa: E402
from common.bus import BusPub, BusSub  # noqa: E402

PROJ_ROOT = "/home/pi/robot"
if PROJ_ROOT not in sys.path:
    sys.path.insert(0, PROJ_ROOT)


PUB = None
SUB_BTN = None
SUB_MS = None

SYSTEM_MODE_TOPIC = "system.mode"
HOME_ITEMS = ["Dema", "Autonomia", "Teleop", "Ustawienia", "Logi"]
LOW_BATTERY_LIMIT = 0.15

state = {
    "screen": "home",
    "cursor": 0,
    "battery": None,
}


def pub(topic, payload):
    global PUB
    if PUB is None:
        PUB = BusPub()
    # kompatybilnie z różnymi implementacjami BusPub
    for m in ("send", "publish", "pub"):
        if hasattr(PUB, m):
            return getattr(PUB, m)(topic, payload)


def pub_stop():
    pub(
        "motion.command",
        {"action": "stop", "source": "manual", "origin": "physical_menu", "request_id": uuid.uuid4().hex},
    )


def pub_menu_state():
    pub(
        "system.menu.state",
        {
            "screen": state["screen"],
            "cursor": state["cursor"],
            "items": HOME_ITEMS if state["screen"] == "home" else [],
            "ts": time.time(),
            "battery": state["battery"],
        },
    )


def low_batt_blocked():
    b = state["battery"]
    return (b is not None) and (b < LOW_BATTERY_LIMIT)


def on_ok():
    if state["screen"] == "home":
        item = HOME_ITEMS[state["cursor"]]
        if item == "Dema":
            if low_batt_blocked():
                return
            pub_stop()
            pub(
                SYSTEM_MODE_TOPIC,
                {"mode": "demos", "demo": "trajectory", "ts": time.time()},
            )
        elif item == "Autonomia":
            if low_batt_blocked():
                return
            pub_stop()
            pub(SYSTEM_MODE_TOPIC, {"mode": "autonomy", "ts": time.time()})
        elif item == "Teleop":
            pub_stop()
            pub(SYSTEM_MODE_TOPIC, {"mode": "teleop", "ts": time.time()})
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


def log(msg):
    print(time.strftime("[%H:%M:%S]"), msg, flush=True)


def _button_event(p):
    btn = (p.get("id") or "").upper()
    ev = (p.get("event") or "").lower()
    if ev == "down":
        if btn == "LEFT":
            on_left()
        elif btn == "RIGHT":
            on_right()
        elif btn == "OK":
            on_ok()
        elif btn == "BACK":
            on_back()


def main():
    global SUB_BTN, SUB_MS
    SUB_BTN, SUB_MS = BusSub("ui.button"), BusSub("motion.state")
    log("Menu: start (buttons + motion.state)")
    last_pub = 0
    latest_motion = {}
    try:
        while True:
            # buttons
            t, p = SUB_BTN.recv(timeout_ms=50)
            if t:
                _button_event(p)
            # battery
            t2, p2 = SUB_MS.recv(timeout_ms=0)
            if t2 and isinstance(p2, dict):
                latest_motion = p2
            sample = battery_observation(latest_motion, now=time.time())
            state["battery"] = sample["value"] if sample["ready"] else None
            state["battery_observation"] = sample
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
