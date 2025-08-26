#!/usr/bin/env python3
"""
E-Stop ON/OFF/STATUS przez plik-flagę, plus natychmiastowy STOP przez broker.
Użycie:
  python3 scripts/estop.py on
  python3 scripts/estop.py off
  python3 scripts/estop.py status
"""

import sys, os, time, json
from pathlib import Path

BASE = Path("/home/pi/robot")
FLAGS = BASE / "data" / "flags"
FLAGS.mkdir(parents=True, exist_ok=True)

ESTOP_FLAG = FLAGS / "estop.on"
PUB_ADDR = os.getenv("BUS_PUB_ADDR", "tcp://127.0.0.1:5555")
TOPIC = os.getenv("MOTION_TOPIC", "motion")

def _pub_stop():
    try:
        import zmq
        ctx = zmq.Context.instance()
        s = ctx.socket(zmq.PUB)
        s.connect(PUB_ADDR)
        time.sleep(0.1)
        s.send_multipart([TOPIC.encode(), json.dumps({"type": "stop"}).encode("utf-8")])
    except Exception:
        pass

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in {"on","off","status"}:
        print("Usage: estop.py on|off|status")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "on":
        ESTOP_FLAG.touch()
        _pub_stop()
        print("E-Stop: ON")
    elif cmd == "off":
        try: ESTOP_FLAG.unlink()
        except FileNotFoundError: pass
        print("E-Stop: OFF")
    else:
        print(f"E-Stop flag exists: {ESTOP_FLAG.exists()}")

if __name__ == "__main__":
    main()
