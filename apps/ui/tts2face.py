#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apps/ui/tts2face.py — mostek TTS→Face
Sub: tts.speak {"text":"...", "voice":"pl"}
Pub: ui.face.set {"expr":"speak"} ... a po czasie -> {"expr":"neutral"}
"""

import os, sys, time, json, threading

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

SUB = BusSub("tts.speak")
PUB = BusPub()

MIN_DUR = float(os.getenv("TTS2FACE_MIN_DUR", "0.8"))   # s
MAX_DUR = float(os.getenv("TTS2FACE_MAX_DUR", "6.0"))   # s
WPS     = float(os.getenv("TTS2FACE_WPS",     "3.0"))   # słowa/s (~180 wpm)

def log(msg):
    print(time.strftime("[%H:%M:%S]"), msg, flush=True)

def estimate_duration(text: str) -> float:
    if not text:
        return MIN_DUR
    words = max(1, len(text.split()))
    dur = words / WPS
    return max(MIN_DUR, min(MAX_DUR, dur))

def pub(topic, payload):
    # zgodnie z Twoim BusPub (scripts/pub.py używa .send)
    for m in ("send", "publish", "pub"):
        if hasattr(PUB, m):
            return getattr(PUB, m)(topic, payload)
    raise AttributeError("BusPub bez send/publish/pub")

def speak_once(text: str):
    dur = estimate_duration(text)
    log(f"TTS→Face: speak {dur:.1f}s: {text!r}")
    try:
        pub("ui.face.set", {"expr":"speak"})
        # można przekazać 'intensity' itp. jeśli UI wspiera
    except Exception as e:
        log(f"pub speak error: {e}")
        return

    def back_to_neutral():
        time.sleep(dur)
        try:
            pub("ui.face.set", {"expr":"neutral"})
        except Exception as e:
            log(f"pub neutral error: {e}")

    threading.Thread(target=back_to_neutral, daemon=True).start()

def main():
    log("tts2face: start (sub tts.speak → pub ui.face.set)")
    while True:
        topic, payload = SUB.recv(timeout_ms=500)
        if topic is None:
            continue
        try:
            msg = payload if isinstance(payload, dict) else json.loads(payload)
            text = (msg.get("text") or "").strip()
            if text:
                speak_once(text)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            log(f"tts2face error: {e}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("tts2face: bye")
