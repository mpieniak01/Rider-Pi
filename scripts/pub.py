#!/usr/bin/env python3
import sys, json, time
from common.bus import BusPub, now_ts
def main():
    topic = sys.argv[1] if len(sys.argv) > 1 else "demo.ping"
    payload = {"ts": now_ts(), "hello": "world"}
    if len(sys.argv) > 2:
        try: payload = json.loads(sys.argv[2])
        except Exception: pass
    pub = BusPub()
    print(f"[PUB] sending to {topic}: {payload}")
    time.sleep(0.1)  # daj SUB-owi się zasubskrybować
    pub.publish(topic, payload)
if __name__ == "__main__":
    main()

