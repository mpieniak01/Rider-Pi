#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apps/motion/main.py — odbiór intent.motion / motion.cmd i wykonanie akcji (DRY, nieblokujące)

Sub:
  intent.motion  {"action":"forward|back|left|right|stop|sit|stand", "speed":0.4, "duration":1.5}
  motion.cmd     {"type":"drive|spin|stop", "dir":"forward|backward|left|right", "speed":0.4, "dur":1.0}

Pub:
  motion.state   {"speed":0.0, "ts":..., "reason":"dur_done|watchdog|periodic", "wd":true?}
"""

import os, sys, time, json

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
SUB_INTENT = BusSub("intent.motion")   # alias (stary temat)
SUB_CMD    = BusSub("motion.cmd")      # kanoniczny temat

# XGO (opcjonalnie)
try:
    from xgolib import XGO
    HAS_XGO = True
except Exception:
    XGO = None
    HAS_XGO = False

g_car = None

LED_IDLE   = [0,0,0]
LED_ACTIVE = [60,40,0]
LED_OK     = [0,80,0]
LED_ERR    = [80,0,0]

# === runtime ===
WATCHDOG_S      = float(os.getenv("MOTION_WATCHDOG_S", "1.5"))
STATE_PERIOD_S  = float(os.getenv("MOTION_STATE_PERIOD_S", "0.5"))
DEFAULT_SPEED   = float(os.getenv("MOTION_DEFAULT_SPEED", "0.5"))
DEFAULT_DUR_S   = float(os.getenv("MOTION_DEFAULT_DUR_S", "1.0"))
WD_MODE         = os.getenv("MOTION_WD_MODE", "strict").lower()  # "strict" | "lease"

# === stan ruchu (nieblokujący) ===
CUR_SPEED   = 0.0                # aktualna prędkość (umowna skala)
UNTIL_TS    = 0.0                # monotoniczny deadline trwania ruchu; 0 = brak
LAST_CMD_TS = time.monotonic()   # kiedy ostatnio przyszła komenda
NEXT_STATE  = time.monotonic()   # kiedy wysłać kolejną telemetrię

def log(msg):
    try:
        print(time.strftime("[%H:%M:%S]"), msg, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((time.strftime("[%H:%M:%S] ")+str(msg)+"\n").encode("utf-8","replace"))
        sys.stdout.flush()

def now_ts():
    return time.time()

def led(color):
    global g_car
    if not g_car:
        return
    try:
        g_car.rider_led(1, color)
        g_car.rider_led(0, color)
    except Exception:
        pass

def init_xgo():
    global g_car
    if not HAS_XGO:
        log("Motion: XGO lib not present — tryb stub.")
        return
    try:
        g_car = XGO("xgorider")
        log("Motion: XGO OK")
    except Exception as e:
        g_car = None
        log(f"Motion: XGO init failed: {e}")

# --- telemetria ---

def _bus_publish(topic: str, payload: dict):
    # kompatybilnie z Twoim BusPub (scripts/pub.py używa .send)
    for m in ("send", "publish", "pub"):
        if hasattr(PUB, m):
            return getattr(PUB, m)(topic, payload)
    raise AttributeError("BusPub nie ma metod send/publish/pub")

def publish_state(speed: float, **extra):
    state = {"speed": round(float(speed), 2), "ts": now_ts()}
    state.update(extra)
    try:
        _bus_publish("motion.state", state)
    except Exception as e:
        log(f"Motion: state pub error: {e}")

# --- mapowania schematów ---

def map_intent_to_motion_state(intent: dict):
    """
    Stary schemat: {"action":"forward|back|left|right|stop|sit|stand","speed","duration"}
    Zwraca: (new_speed, until_ts)
    """
    a = (intent.get("action") or "").lower()
    speed = float(intent.get("speed", DEFAULT_SPEED))
    dur   = float(intent.get("duration", DEFAULT_DUR_S))

    if a in ("stop", "sit", "stand"):
        return 0.0, 0.0

    if a == "forward":
        return max(speed, 0.0), (time.monotonic() + max(dur, 0.0))
    if a == "back":
        return -max(speed, 0.0), (time.monotonic() + max(dur, 0.0))
    if a in ("left", "right"):
        # prosta symulacja spin/skrętu jako ruchu z dodatnią prędkością
        return max(speed, 0.0), (time.monotonic() + max(dur, 0.0))

    return None, None

def map_cmd_to_motion_state(cmd: dict):
    """
    Nowy schemat: {"type":"drive|spin|stop","dir":"forward|backward|left|right","speed","dur"}
    Zwraca: (new_speed, until_ts)
    """
    t = (cmd.get("type") or "").lower()
    if t == "stop":
        return 0.0, 0.0

    speed = float(cmd.get("speed", DEFAULT_SPEED))
    dur   = float(cmd.get("dur", DEFAULT_DUR_S))
    dirv  = (cmd.get("dir") or "").lower()

    if t == "drive":
        if dirv == "backward":
            return -max(speed, 0.0), (time.monotonic() + max(dur, 0.0))
        return max(speed, 0.0), (time.monotonic() + max(dur, 0.0))

    if t == "spin":
        return max(speed, 0.0), (time.monotonic() + max(dur, 0.0))

    # arc/servo — dojdą później
    return None, None

# --- przyjęcie komendy (nieblokujące ustawienie stanu) ---

def apply_motion(new_speed: float, until_ts: float):
    global CUR_SPEED, UNTIL_TS
    CUR_SPEED = float(new_speed)
    UNTIL_TS  = float(until_ts)
    led(LED_ACTIVE)
    publish_state(CUR_SPEED)  # start ruchu

def handle_payload(topic: str, payload):
    global LAST_CMD_TS
    LAST_CMD_TS = time.monotonic()

    try:
        msg = payload if isinstance(payload, dict) else json.loads(payload)
    except Exception as e:
        log(f"Motion: bad JSON on {topic}: {e}")
        return

    if topic == "intent.motion" or ("action" in msg and not msg.get("type")):
        log(f"Motion: intent → {msg}")
        ns, ut = map_intent_to_motion_state(msg)
    else:
        log(f"Motion: cmd → {msg}")
        ns, ut = map_cmd_to_motion_state(msg)

    if ns is not None and ut is not None:
        apply_motion(ns, ut)
    else:
        log("Motion: unsupported/ignored payload")

# --- pętla główna ---

def main():
    global NEXT_STATE, CUR_SPEED, UNTIL_TS

    init_xgo()
    log(f"Motion: start (sub intent.motion + motion.cmd) [WD={WATCHDOG_S:.1f}s, mode={WD_MODE}]")

    NEXT_STATE = time.monotonic()  # telemetria co STATE_PERIOD_S

    while True:
        # odbiór najpierw z kanonicznego tematu (krótko), potem ze starego
        topic, payload = SUB_CMD.recv(timeout_ms=10)
        if topic is None:
            topic, payload = SUB_INTENT.recv(timeout_ms=10)
        if topic is not None:
            try:
                handle_payload(topic, payload)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                led(LED_ERR)
                log(f"Motion: error: {e}")

        now_mono = time.monotonic()

        # 1) auto-stop po upłynięciu 'dur'
        if UNTIL_TS and now_mono >= UNTIL_TS and CUR_SPEED != 0.0:
            CUR_SPEED = 0.0
            UNTIL_TS  = 0.0
            led(LED_OK)
            publish_state(0.0, reason="dur_done")

        # 2) watchdog — brak komend > WATCHDOG_S
        if (now_mono - LAST_CMD_TS) > WATCHDOG_S and CUR_SPEED != 0.0:
            if WD_MODE == "lease" and UNTIL_TS and now_mono < UNTIL_TS:
                # w trybie lease NIE przerywamy, jeśli jeszcze trwa 'dur'
                pass
            else:
                CUR_SPEED = 0.0
                UNTIL_TS  = 0.0
                log(f"Motion: Watchdog STOP (> {WATCHDOG_S:.1f}s bez komend)")
                led(LED_OK)
                publish_state(0.0, wd=True, reason="watchdog")

        # 3) okresowa telemetria (żeby UI widziało „życie”)
        if now_mono >= NEXT_STATE:
            publish_state(CUR_SPEED, reason="periodic")
            NEXT_STATE = now_mono + STATE_PERIOD_S

        time.sleep(0.005)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        led(LED_IDLE)
        log("Motion: bye")
