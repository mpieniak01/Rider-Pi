#!/usr/bin/env python3
import os, sys

# dopnij root projektu do sys.path, żeby "common" było widoczne
PROJ_ROOT = "/home/pi/robot"
if PROJ_ROOT not in sys.path:
    sys.path.insert(0, PROJ_ROOT)

from common.bus import BusSub

# spróbuj wymusić UTF-8 na stdout (Python 3.7+)
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

def safe_print(s: str):
    try:
        print(s, flush=True)
    except UnicodeEncodeError:
        # fallback: wypisz bajty UTF-8 bez wywalania się
        sys.stdout.buffer.write((s + "\n").encode("utf-8", "replace"))
        sys.stdout.flush()

def main():
    topic = sys.argv[1] if len(sys.argv) > 1 else "demo.ping"
    sub = BusSub(topic)
    safe_print(f"[SUB] listening on topic: {topic}")
    while True:
        t, p = sub.recv()
        if t is None:
            continue
        # JSON może mieć znaki spoza ISO-8859-2; renderuj bez ASCII-escape
        try:
            import json
            payload_str = json.dumps(p, ensure_ascii=False)
        except Exception:
            payload_str = str(p)
        safe_print(f"[SUB] {t}: {payload_str}")

if __name__ == "__main__":
    main()
