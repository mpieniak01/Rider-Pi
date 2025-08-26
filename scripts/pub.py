#!/usr/bin/env python3
"""
Demo trajektorii (PUB -> broker):
- forward → spin right → backward → stop
ENV:
  BUS_PUB_ADDR     (default tcp://127.0.0.1:5555)
  MOTION_TOPIC     (default motion)
  DEMO_RATE_HZ     (default 10)
  DEMO_SPEED_FWD   (default 0.25)
  DEMO_SPEED_ROT   (default 0.25)
  DEMO_SEG_SEC     (default 2.0)
"""

import os
import time
import json
import zmq

PUB_ADDR = os.getenv("BUS_PUB_ADDR", "tcp://127.0.0.1:5555")
TOPIC    = os.getenv("MOTION_TOPIC", "motion")
RATE_HZ  = float(os.getenv("DEMO_RATE_HZ", "10"))
DT       = 1.0 / RATE_HZ

SPEED_FWD = float(os.getenv("DEMO_SPEED_FWD", "0.25"))
SPEED_ROT = float(os.getenv("DEMO_SPEED_ROT", "0.25"))
SEG_SEC   = float(os.getenv("DEMO_SEG_SEC", "2.0"))

def _mk_pub(addr: str):
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.PUB)
    sock.connect(addr)
    return sock

def _send(sock, msg: dict):
    payload = json.dumps(msg).encode("utf-8")
    sock.send_multipart([TOPIC.encode("utf-8"), payload])

def _drive_for(sock, lx: float, az: float, dur: float):
    t0 = time.time()
    while time.time() - t0 < dur:
        _send(sock, {"type": "drive", "lx": lx, "az": az})
        time.sleep(DT)

def main():
    print(f"[DEMO] Connecting PUB to {PUB_ADDR} topic='{TOPIC}'")
    sock = _mk_pub(PUB_ADDR)

    # rozgrzewka subskrybentów
    time.sleep(0.5)

    try:
        print("[DEMO] forward")
        _drive_for(sock, SPEED_FWD, 0.0, SEG_SEC)

        print("[DEMO] spin right")
        _drive_for(sock, 0.0, SPEED_ROT, SEG_SEC)

        print("[DEMO] backward")
        _drive_for(sock, -SPEED_FWD, 0.0, SEG_SEC)

        print("[DEMO] stop")
        _send(sock, {"type": "stop"})
        time.sleep(0.1)
    finally:
        # dodatkowy stop na wszelki wypadek
        _send(sock, {"type": "stop"})
        print("[DEMO] done")

if __name__ == "__main__":
    main()
