#!/usr/bin/env python3
"""
Sniffer SUB — podgląd ramek wychodzących z brokera (XPUB).
Domyślnie:
  ADDR  = tcp://127.0.0.1:5556
  TOPIC = motion
Użycie:
  python3 scripts/sub_dump.py                 # dump 'motion'
  TOPIC="*" python3 scripts/sub_dump.py       # dump wszystkie
  TOPIC="vision" python3 scripts/sub_dump.py  # dump 'vision'
"""

import os
import time
import zmq

ADDR  = os.getenv("BUS_SUB_ADDR", "tcp://127.0.0.1:5556")
TOPIC = os.getenv("TOPIC", os.getenv("MOTION_TOPIC", "motion"))

ctx = zmq.Context.instance()
sub = ctx.socket(zmq.SUB)
sub.connect(ADDR)

if TOPIC == "*" or TOPIC == "":
    sub.setsockopt(zmq.SUBSCRIBE, b"")
    fmt = "(all topics)"
else:
    sub.setsockopt(zmq.SUBSCRIBE, TOPIC.encode("utf-8"))
    fmt = f"(topic='{TOPIC}')"

print(f"[DUMP] SUB {ADDR} {fmt}")

while True:
    parts = sub.recv_multipart()
    ts = time.strftime("%H:%M:%S")
    if len(parts) >= 2:
        topic = parts[0].decode("utf-8", errors="replace")
        payload = parts[1].decode("utf-8", errors="replace")
        print(f"{ts}  [{topic}]  {payload}")
    else:
        print(f"{ts}  frames={len(parts)} :: {[p[:50] for p in parts]}")
