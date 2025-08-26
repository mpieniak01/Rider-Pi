#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apps/motion/main.py — Motion loop (PUB/SUB), XGO adapter, watchdog i telemetria.

Sub:
  - intent.motion  {"action":"forward|back|left|right|stop", "speed":0.4, "duration":1.5}
    (alias wsteczny; mapujemy na kanoniczne)
  - motion.cmd     {"type":"drive|spin|stop", ...}

Pub:
  - motion.state   {"speed":0.0, "ts":..., "reason":"periodic|dur_done|watchdog", "wd":true, "battery":0.82?}

Uwaga:
- Fizyczny ruch jest wykonywany tylko, gdy MOTION_ENABLE=1 (adapter XGO honoruje tę flagę).
- W trybie "lease" watchdog nie przerywa ruchu (kończy się na 'dur' → dur_done).
"""

import os, sys, time, json, math
from typing import Optional

# --- ścieżka projektu ---
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
from apps.motion.xgo_adapter import XgoAdapter

# --- BUS ---
PUB = BusPub()
SUB_INTENT = BusSub("intent.motion")   # alias legacy
SUB_CMD    = BusSub("motion.cmd")      # kanoniczny

# --- XGO adapter ---
XGO = XgoAdapter()
HAS_XGO = XGO.ok()

# --- LED kolory (RGB) ---
LED_IDLE   = (0, 0, 0)
LED_ACTIVE = (60, 40, 0)   # pomarańcz
LED_OK     = (0, 80, 0)    # zielony
LED_ERR    = (80, 0, 0)    # czerwony

def led(color):
    try:
        # 1 i 0 (obie)
        XGO.led(1, color)
        XGO.led(0, color)
    except Exception:
        pass

def log(msg):
    try:
        print(time.strftime("[%H:%M:%S]"), msg, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((time.strftime("[%H:%M:%S] ")+str(msg)+"\n").encode("utf-8","replace"))
        sys.stdout.flush()

def _bus_publish(topic: str, payload: dict):
    # kompatybilnie z naszym BusPub (scripts/pub.py używa .send)
    for m in ("send", "publish", "pub"):
        if hasattr(PUB, m):
            return getattr(PUB, m)(topic, payload)
    raise AttributeError("BusPub bez send/publish/pub")

# --- Watchdog i telemetria ---
WD_S   = float(os.getenv("MOTION_WATCHDOG_S", "1.5"))
WD_MODE = (os.getenv("MOTION_WD_MODE", "strict") or "strict").lower().strip()  # "strict"|"lease"
TICK_S = 0.5  # okres publikacji "periodic"

last_cmd_ts: float = 0.0
run_until_ts: Optional[float] = None
cur_speed: float = 0.0
cur_mode: str = "idle"   # "idle"|"drive"|"spin"

def pub_state(speed: float, *, reason: Optional[str]=None):
    msg = {"speed": float(speed), "ts": time.time()}
    if reason:
        msg["reason"] = reason
    # wd info
    if WD_S > 0:
        msg["wd"] = (WD_MODE in ("strict", "lease"))
    # bateria (jeśli dostępna)
    try:
        bat = XGO.battery()
        if bat is not None:
            msg["battery"] = round(float(bat), 3)  # 0..1
    except Exception:
        pass
    _bus_publish("motion.state", msg)

def now() -> float:
    return time.time()

# --- Mapowania legacy INTENT → kanoniczne ---
def handle_intent(payload: dict):
    """Obsługa starego tematu intent.motion."""
    action = (payload.get("action") or "").lower().strip()
    speed  = float(payload.get("speed", 0.4))
    dur    = float(payload.get("duration", 1.0))

    if action in ("forward", "fwd", "ahead"):
        handle_cmd({"type":"drive", "dir":"forward", "speed":speed, "dur":dur})
    elif action in ("back", "backward", "rev"):
        handle_cmd({"type":"drive", "dir":"backward", "speed":speed, "dur":dur})
    elif action in ("left", "turnleft"):
        handle_cmd({"type":"spin", "dir":"left", "speed":speed, "dur":dur})
    elif action in ("right", "turnright"):
        handle_cmd({"type":"spin", "dir":"right", "speed":speed, "dur":dur})
    elif action in ("stop", "halt"):
        handle_cmd({"type":"stop"})
    else:
        log(f"Motion: unknown intent.action={action}")

# --- Kanoniczne komendy ---
def do_stop(reason: str):
    global cur_speed, cur_mode, run_until_ts
    try:
        XGO.stop()
    except Exception:
        pass
    cur_speed = 0.0
    cur_mode = "idle"
    run_until_ts = None
    led(LED_OK if reason in ("dur_done","periodic") else LED_IDLE)
    pub_state(0.0, reason=reason)

def do_drive(dir_: str, speed: float, dur: float):
    global cur_speed, cur_mode, run_until_ts, last_cmd_ts
    s = max(0.0, min(1.0, float(speed)))
    d = max(0.0, float(dur))
    dir_norm = "forward" if dir_.lower().startswith("f") else "backward"
    log(f"Motion: drive dir={dir_norm} speed={s} dur={d}")
    led(LED_ACTIVE)
    try:
        XGO.drive(dir_norm, s, dur=d, block=False)
    except Exception as e:
        log(f"Motion: drive error: {e}")
        led(LED_ERR)
    cur_speed = s if s > 0 else 0.0
    cur_mode = "drive" if s > 0 else "idle"
    run_until_ts = (now() + d) if d > 0 else None
    last_cmd_ts = now()
    pub_state(cur_speed)

def do_spin(dir_: str, speed: float, dur: float, deg: Optional[float]=None):
    global cur_speed, cur_mode, run_until_ts, last_cmd_ts
    s = max(0.0, min(1.0, float(speed)))
    d = max(0.0, float(dur))
    side = "left" if dir_.lower().startswith("l") else "right"
    log(f"Motion: spin dir={side} speed={s} dur={d}")
    led(LED_ACTIVE)
    try:
        XGO.spin(side, s, dur=d, deg=deg, block=False)
    except Exception as e:
        log(f"Motion: spin error: {e}")
        led(LED_ERR)
    cur_speed = s if s > 0 else 0.0
    cur_mode = "spin" if s > 0 else "idle"
    run_until_ts = (now() + d) if d > 0 else None
    last_cmd_ts = now()
    pub_state(cur_speed)

def handle_cmd(payload: dict):
    t = (payload.get("type") or "").lower().strip()
    if t == "stop":
        do_stop("cmd_stop")
        return
    if t == "drive":
        do_drive(payload.get("dir","forward"), float(payload.get("speed", 0.4)), float(payload.get("dur", 0.0)))
        return
    if t == "spin":
        do_spin(payload.get("dir","left"), float(payload.get("speed", 0.4)), float(payload.get("dur", 0.0)), payload.get("deg"))
        return
    # przyszłościowo: arc/servo/action...
    log(f"Motion: unknown cmd.type={t}")

def main():
    log(f"Motion: XGO {'OK' if HAS_XGO else 'stub'}")
    log(f"Motion: start (sub intent.motion + motion.cmd) [WD={WD_S:.1f}s, mode={WD_MODE}]")

    tick_ts = 0.0
    try:
        while True:
            # --- odbiór komend ---
            topic1, payload1 = SUB_INTENT.recv(timeout_ms=0)
            if topic1:
                log(f"Motion: intent → {payload1}")
                try:
                    handle_intent(payload1 or {})
                except Exception as e:
                    led(LED_ERR); log(f"Motion: intent error: {e}")

            topic2, payload2 = SUB_CMD.recv(timeout_ms=200)
            if topic2:
                log(f"Motion: cmd → {payload2}")
                try:
                    handle_cmd(payload2 or {})
                except Exception as e:
                    led(LED_ERR); log(f"Motion: cmd error: {e}")

            # --- zegar / telemetria perio. ---
            t = now()
            if t - tick_ts >= TICK_S:
                tick_ts = t
                pub_state(cur_speed, reason="periodic")

                # zakończenie po czasie (dur_done)
                if run_until_ts and t >= run_until_ts and cur_speed > 0:
                    do_stop("dur_done")

                # watchdog strict
                if WD_MODE == "strict" and cur_speed > 0 and WD_S > 0 and (t - last_cmd_ts) > WD_S:
                    log("Motion: Watchdog STOP (> WD bez komend)")
                    do_stop("watchdog")
    except KeyboardInterrupt:
        pass
    finally:
        try:
            led(LED_IDLE)
        except Exception:
            pass
        log("Motion: bye")

if __name__ == "__main__":
    main()
