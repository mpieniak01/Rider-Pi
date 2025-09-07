#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTP → ZMQ bridge dla Rider-Pi (zgodny z motion_bridge.py) + kompatybilny /control.

Endpointy:
  GET  /api/move?dir=forward|backward|left|right[&v=0..1][&w=0..1][&t=sek]
  GET  /api/stop
  GET  /api/balance?on=0|1
  GET  /api/height?h=INT
  GET  /healthz
  POST /control    {type: drive|spin|stop, ...}  // kompatybilne z dashboardem
"""

import os, json, time
from flask import Flask, request, jsonify
import zmq

BUS_ADDR   = os.getenv("BUS_PUB_ADDR", "tcp://127.0.0.1:5555")
TOPIC_MOVE = os.getenv("TOPIC_MOVE", "cmd.move")
TOPIC_STOP = os.getenv("TOPIC_STOP", "cmd.stop")
V_DEF      = float(os.getenv("WEB_V_DEFAULT", "0.10"))  # domyślny vx (0..1)
W_DEF      = float(os.getenv("WEB_W_DEFAULT", "0.18"))  # domyślny yaw/az (0..1)
T_DEF      = float(os.getenv("WEB_T_DEFAULT", "0.15"))  # domyślny czas ruchu [s]

_ctx = zmq.Context.instance()
_pub = _ctx.socket(zmq.PUB)
# jeżeli chcesz uruchamiać ten mostek jako broker PUB — ustaw WEB_BIND_PUB=1
_pub.bind(BUS_ADDR) if os.getenv("WEB_BIND_PUB", "0") == "1" else _pub.connect(BUS_ADDR)

# XGO adapter (opcjonalnie – best effort)
try:
    from apps.motion.xgo_adapter import XgoAdapter  # type: ignore
    _ADA = XgoAdapter()
except Exception:
    _ADA = None

app = Flask(__name__)

def _send(topic: str, obj: dict):
    o = dict(obj); o.setdefault("ts", time.time())
    msg = f"{topic} {json.dumps(o, ensure_ascii=False)}"
    _pub.send_string(msg)

def _clamp01(v) -> float:
    try: v = float(v)
    except Exception: return 0.0
    return 0.0 if v < 0 else 1.0 if v > 1 else v

# --- CORS: pozwól na zapytania z dashboardu na innym porcie (np. :8080) ---
@app.after_request
def _add_cors(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    resp.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    return resp

@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify({"ok": True})

# --- /api/* (stare, GET) ---
@app.route("/api/move", methods=["GET"])
def api_move():
    d = (request.args.get("dir") or "").lower()
    v = _clamp01(request.args.get("v", default=V_DEF, type=float))
    w = _clamp01(request.args.get("w", default=W_DEF, type=float))
    t = float(request.args.get("t", default=T_DEF))
    if d == "forward":
        _send(TOPIC_MOVE, {"vx": +v, "vy": 0.0, "yaw": 0.0, "duration": t})
    elif d == "backward":
        _send(TOPIC_MOVE, {"vx": -v, "vy": 0.0, "yaw": 0.0, "duration": t})
    elif d == "left":
        _send(TOPIC_MOVE, {"vx": 0.0, "vy": 0.0, "yaw": +w, "duration": t})
    elif d == "right":
        _send(TOPIC_MOVE, {"vx": 0.0, "vy": 0.0, "yaw": -w, "duration": t})
    else:
        return jsonify({"ok": False, "err": "bad dir"}), 400
    return jsonify({"ok": True, "dir": d, "v": v, "w": w, "t": t})

@app.route("/api/stop", methods=["GET"])
def api_stop():
    _send(TOPIC_STOP, {})
    return jsonify({"ok": True})

@app.route("/api/balance", methods=["GET"])
def api_balance():
    on = request.args.get("on", default="1")
    is_on = on in ("1","true","True","yes","on")
    if _ADA is None:
        return jsonify({"ok": False, "err": "adapter_unavailable"}), 501
    try:
        _ADA.enable_balance(is_on)
        return jsonify({"ok": True, "on": is_on})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 500

@app.route("/api/height", methods=["GET"])
def api_height():
    h = request.args.get("h", type=int)
    if h is None:
        return jsonify({"ok": False, "err": "missing h"}), 400
    if _ADA is None:
        return jsonify({"ok": False, "err": "adapter_unavailable"}), 501
    try:
        _ADA.set_height(h)
        return jsonify({"ok": True, "h": int(h)})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 500

# --- /control (NOWE, POST) kompatybilne z dashboardem :8080 ---
@app.route("/control", methods=["POST","OPTIONS"])
def control_post():
    if request.method == "OPTIONS":
        return ("", 204)  # preflight CORS
    data = request.get_json(silent=True) or {}
    rid  = data.get("rid") or f"{int(time.time()*1000)&0xffffffff:08x}"
    typ  = (data.get("type") or "").lower()

    if typ == "stop":
        _send(TOPIC_STOP, {"rid": rid})
        return jsonify({"ok": True, "rid": rid})

    elif typ == "drive":
        # dashboard: {"type":"drive","lx":0.05,"az":0,"dur":0.12}
        lx  = float(data.get("lx", 0.0) or 0.0)    # prędkość do przodu/tyłu (-1..1)
        az  = float(data.get("az", 0.0) or 0.0)    # prędkość obrotu (-1..1)
        dur = float(data.get("dur", T_DEF) or T_DEF)
        vx  = _clamp01(abs(lx)) * (1 if lx >= 0 else -1)
        yaw = _clamp01(abs(az)) * (1 if az >= 0 else -1)
        dur = max(0.05, min(dur, T_DEF))
        payload = {"rid": rid, "vx": vx, "vy": 0.0, "yaw": yaw, "duration": dur}
        _send(TOPIC_MOVE, payload)
        return jsonify({"ok": True, "rid": rid, "sent": payload})

    elif typ == "spin":
        # dashboard: {"type":"spin","dir":"left|right","speed":0..1,"dur":s}
        dir_ = (data.get("dir") or "").lower()
        spd  = _clamp01(data.get("speed", W_DEF))
        dur  = float(data.get("dur", T_DEF) or T_DEF)
        yaw  = +spd if dir_ in ("left","l") else -spd
        dur  = max(0.05, min(dur, T_DEF))
        payload = {"rid": rid, "vx": 0.0, "vy": 0.0, "yaw": yaw, "duration": dur}
        _send(TOPIC_MOVE, payload)
        return jsonify({"ok": True, "rid": rid, "sent": payload})

    else:
        return jsonify({"ok": False, "err": "bad type", "got": typ}), 400

if __name__ == "__main__":
    host = os.getenv("WEB_HOST", "127.0.0.1")
    port = int(os.getenv("WEB_PORT", "8080"))
    app.run(host=host, port=port, threaded=True)
