#!/usr/bin/env python3
# Minimalne API: /healthz i /state (kompatybilne z Flask 1.x i 2.x)
import os, time, json, threading
from typing import Any, Dict
from flask import Flask, jsonify

try:
    import zmq
except Exception:
    zmq = None

BUS_SUB_PORT = int(os.getenv("BUS_SUB_PORT", "5556"))
STATUS_API_PORT = int(os.getenv("STATUS_API_PORT", "8080"))

app = Flask(__name__)

# kompatybilny dekorator GET (Flask 1.x nie ma app.get)
def route_get(path):
    if hasattr(app, "get"):
        return app.get(path)
    return app.route(path, methods=["GET"])

_last_state: Dict[str, Any] = {"present": False, "confidence": 0.0, "ts": None}
_last_msg_ts: float = 0.0
_last_hb_ts: float = 0.0
_start_ts: float = time.time()

def _sub_loop():
    """Subskrybuje vision.* z busa i aktualizuje ostatni stan/heartbeat."""
    global _last_state, _last_msg_ts, _last_hb_ts
    if zmq is None:
        print("[api] pyzmq not available; bus disabled", flush=True)
        return
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.SUB)
    s.connect(f"tcp://127.0.0.1:{BUS_SUB_PORT}")
    s.setsockopt_string(zmq.SUBSCRIBE, "vision.")
    print(f"[api] SUB connected tcp://127.0.0.1:{BUS_SUB_PORT}", flush=True)
    while True:
        try:
            msg = s.recv_string()
            topic, payload = msg.split(" ", 1)
            print(f"[api] got: {topic}", flush=True)
            now = time.time()
            _last_msg_ts = now
            try:
                data = json.loads(payload)
            except Exception:
                data = {}
            if topic == "vision.state":
                _last_state = {
                    "present": bool(data.get("present", False)),
                    "confidence": float(data.get("confidence", 0.0)),
                    "ts": float(data.get("ts", now)),
                }
            elif topic == "vision.dispatcher.heartbeat":
                _last_hb_ts = now
        except Exception:
            time.sleep(0.05)

@route_get("/healthz")
def healthz():
    now = time.time()
    hb_age = None if _last_hb_ts == 0 else now - _last_hb_ts
    msg_age = None if _last_msg_ts == 0 else now - _last_msg_ts
    bus_ok = (hb_age is not None and hb_age < 10.0) or (msg_age is not None and msg_age < 10.0)
    return jsonify({
        "status": "ok" if bus_ok else "degraded",
        "uptime_s": round(now - _start_ts, 3),
        "bus": {
            "last_msg_age_s": None if msg_age is None else round(msg_age, 3),
            "last_heartbeat_age_s": None if hb_age is None else round(hb_age, 3),
        },
    })

@route_get("/state")
def state():
    now = time.time()
    ts = _last_state.get("ts")
    age = None if ts is None else max(0.0, now - float(ts))
    return jsonify({
        "present": bool(_last_state.get("present", False)),
        "confidence": float(_last_state.get("confidence", 0.0)),
        "ts": ts,
        "age_s": None if age is None else round(age, 3),
    })

def main():
    threading.Thread(target=_sub_loop, daemon=True).start()
    # Flask 1.x/2.x kompatybilnie:
    app.run(host="0.0.0.0", port=STATUS_API_PORT, threaded=True, use_reloader=False)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
