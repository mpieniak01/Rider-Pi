#!/usr/bin/env python3
import os, time, zmq

ADDR  = os.getenv("BUS_SUB_ADDR", "tcp://127.0.0.1:5556")
TOPIC = os.getenv("MOTION_STATE_TOPIC", "motion.state").encode()

ctx = zmq.Context.instance()
sub = ctx.socket(zmq.SUB)
sub.connect(ADDR)
sub.setsockopt(zmq.SUBSCRIBE, TOPIC)

print(f"[STATE] SUB {ADDR} topic='{TOPIC.decode()}'")
while True:
    t = time.strftime("%H:%M:%S")
    topic, payload = sub.recv_multipart()
    print(f"{t} {topic.decode()} :: {payload.decode()[:300]}")
