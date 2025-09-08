#!/usr/bin/env python3
import zmq, json, time

def main():
    ctx = zmq.Context.instance()

    # SUB: legacy od dashboardu (broker SUB:5556)
    sub = ctx.socket(zmq.SUB)
    sub.connect("tcp://127.0.0.1:5556")
    sub.setsockopt_string(zmq.SUBSCRIBE, "motion.cmd")

    # PUB: nowe komendy do bridge (broker PUB:5555)
    pub = ctx.socket(zmq.PUB)
    pub.connect("tcp://127.0.0.1:5555")

    print("[shim] START: motion.cmd → cmd.move", flush=True)

    while True:
        msg = sub.recv_string()
        try:
            topic, payload = msg.split(" ", 1)
            data = json.loads(payload)
        except Exception:
            data = {}

        d   = (data.get("dir") or "").lower()
        v   = float(data.get("v", 0.0) or 0.0)
        w   = float(data.get("w", 0.0) or 0.0)
        t   = float(data.get("t", 0.12) or 0.12)
        rid = data.get("rid")

        vx  = +v if d == "forward"  else (-v if d == "backward" else 0.0)
        yaw = +w if d == "left"     else (-w if d == "right"    else 0.0)

        out = {"vx": vx, "vy": 0.0, "yaw": yaw, "duration": t, "rid": rid, "ts": time.time()}

        pub.send_string(f"cmd.move {json.dumps(out, ensure_ascii=False)}")
        print("[shim] motion.cmd → cmd.move:", out, flush=True)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[shim] bye.", flush=True)
