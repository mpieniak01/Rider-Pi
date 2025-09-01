#!/usr/bin/env python3
"""
Użycie:
  python3 tools/pub.py motion.state '{"stopped": true, "last_cmd_age_ms": 1500}'
  python3 tools/pub.py vision.state '{"moving": false, "human": true}'
ENV:
  BUS_PUB_ADDR (default tcp://127.0.0.1:5555)
"""
import os, sys, json, time, argparse
import zmq

PUB_ADDR = os.getenv("BUS_PUB_ADDR", "tcp://127.0.0.1:5555")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("topic")
    ap.add_argument("payload")
    ap.add_argument("-n", "--repeat", type=int, default=1)
    args = ap.parse_args()

    try:
        data = json.loads(args.payload)
    except Exception:
        data = {"text": args.payload}

    ctx = zmq.Context.instance()
    pub = ctx.socket(zmq.PUB)
    pub.connect(PUB_ADDR)

    time.sleep(0.2)
    payload = json.dumps(data).encode("utf-8")
    topic_b = args.topic.encode("utf-8")

    for _ in range(max(1, args.repeat)):
        pub.send_multipart([topic_b, payload])
        if args.repeat > 1:
            time.sleep(0.02)

    print(f"[PUB] sent → {args.topic}: {data}")

if __name__ == "__main__":
    main()