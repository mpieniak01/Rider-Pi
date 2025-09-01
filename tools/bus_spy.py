#!/usr/bin/env python3
import os, zmq, time
BUS_SUB_PORT = int(os.getenv("BUS_SUB_PORT","5556"))
ctx = zmq.Context.instance()
s = ctx.socket(zmq.SUB)
s.connect(f"tcp://127.0.0.1:{BUS_SUB_PORT}")
for t in ("cmd.", "motion.", "vision."):
    s.setsockopt_string(zmq.SUBSCRIBE, t)
print(f"[spy] listening on {BUS_SUB_PORT} …")
while True:
    try:
        msg = s.recv_string()
        print(time.strftime("[%H:%M:%S]"), msg, flush=True)
    except KeyboardInterrupt:
        break
