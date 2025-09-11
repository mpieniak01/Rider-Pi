#!/usr/bin/env python3
import os, time, json
import zmq

PUB_PORT = int(os.getenv("BUS_PUB_PORT", "5555"))

ctx = zmq.Context.instance()
pub = ctx.socket(zmq.PUB)
pub.setsockopt(zmq.LINGER, 0)
pub.connect(f"tcp://127.0.0.1:{PUB_PORT}")

def send(topic, payload):
    s = f"{topic} {json.dumps(payload)}"
    pub.send_string(s)
    print("sent:", s, flush=True)

# Rozgrzewka – daj SUB-om chwilę, wyślij „puste” info parę razy
time.sleep(0.3)
for _ in range(3):
    send("cmd.motion.ping", {"ts": time.time()})
    time.sleep(0.1)

# Właściwe komendy (każdą wyślij 2x z odstępem)
send("cmd.motion.forward",  {"speed": 12, "runtime": 1.0}); time.sleep(0.2)
send("cmd.motion.forward",  {"speed": 12, "runtime": 1.0}); time.sleep(1.4)

send("cmd.motion.turn_left", {"speed": 20, "runtime": 0.8}); time.sleep(0.2)
send("cmd.motion.turn_left", {"speed": 20, "runtime": 0.8}); time.sleep(1.0)

send("cmd.motion.stop",     {}); time.sleep(0.2)
send("cmd.motion.stop",     {})
