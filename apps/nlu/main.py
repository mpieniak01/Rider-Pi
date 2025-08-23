#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apps/nlu/main.py — NLU (reguły PL) → intent.motion + krótkie potwierdzenie tts.speak

Sub:  audio.transcript  payload: {"text":"...", "lang":"pl", "ts":..., "source":"voice"}
Pub:  intent.motion     payload: {"action":"forward|back|left|right|stop|sit|stand", "speed":0.4, "duration":1.5}
     tts.speak         payload: {"text":"..."}  (krótkie potwierdzenia)
"""

import os, sys, time

PROJ_ROOT = "/home/pi/robot"
if PROJ_ROOT not in sys.path:
    sys.path.insert(0, PROJ_ROOT)

# bezpieczne printy (ISO-8859-2 friendly)
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

from common.bus import BusPub, BusSub, now_ts
from common.nlu_shared import parse_motion_intent, confirm_text

PUB = BusPub()
SUB = BusSub("audio.transcript")

def log(msg):
    try:
        print(time.strftime("[%H:%M:%S]"), msg, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((time.strftime("[%H:%M:%S] ")+str(msg)+"\n").encode("utf-8","replace"))
        sys.stdout.flush()

def main():
    log("NLU: start (sub audio.transcript -> pub intent.motion)")
    while True:
        topic, payload = SUB.recv(timeout_ms=500)
        if topic is None:
            continue
        text = (payload or {}).get("text", "")
        if not text:
            continue

        intent = parse_motion_intent(text)
        if intent:
            intent["ts"] = now_ts()
            PUB.publish("intent.motion", intent)
            PUB.publish("tts.speak", {"text": confirm_text(intent)})
            log(f"INTENT: {intent}")
        else:
            log(f"NLU: brak dopasowania (ruch) dla: {text!r}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("NLU: bye")
