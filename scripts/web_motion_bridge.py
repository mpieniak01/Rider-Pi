#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTP → ZMQ bridge dla ruchu Rider-Pi.

Endpointy:
  GET /api/move?dir=forward|backward|left|right[&v=0..1][&w=0..1]
  GET /api/stop
  GET /api/balance?on=0|1
  GET /api/height?h=INT

UWAGA: Bridge tylko PUB-uje na bus. Pętla ruchu musi być uruchomiona oddzielnie.
"""

import os
import json
from flask import Flask, request, jsonify

BUS_ADDR   = os.getenv("BUS_PUB_ADDR", "tcp://127.0.0.1:5555")
TOPIC      = os.getenv("MOTION_TOPIC", "motion")
V_DEF      = float(os.getenv("WEB_V_DEFAULT", "0.10"))  # domyślny lx
W_DEF      = float(os.getenv("WEB_W_DEFAULT", "0.18"))  # domyślny az

import zmq
_ctx = zmq.Context.instance()
_pub = _ctx.socket(zmq.PUB)
_pub.bind(BUS_ADDR) if os.getenv("WEB_BIND_PUB","0")=="1" else _pub.connect(BUS_ADDR)

# dla balance/height użyjemy adaptera bez ruchu
from apps.motion.xgo_adapter import XgoAdapter
_ADA = XgoAdapter()

app = Flask(__name__)

def pub(cmd: dict):
    _pub.send_multipart([TOPIC.encode("utf-8"), json.dumps(cmd, ensure_ascii=False).encode("utf-8")])

@app.get("/api/move")
def api_move():
    d = (request.args.get("dir") or "").lower()
    v = request.args.get("v", type=float) or V_DEF
    w = request.args.get("w", type=float) or W_DEF
    if d == "forward":
        pub({"type":"drive","lx": +abs(v), "az": 0.0})
    elif d == "backward":
        pub({"type":"drive","lx": -abs(v), "az": 0.0})
    elif d == "left":
        pub({"type":"drive","lx": 0.0, "az": +abs(w)})
    elif d == "right":
        pub({"type":"drive","lx": 0.0, "az": -abs(w)})
    else:
        return jsonify({"ok":False,"err":"bad dir"}), 400
    return jsonify({"ok":True,"dir":d,"v":v,"w":w})

@app.get("/api/stop")
def api_stop():
    pub({"type":"stop"})
    return jsonify({"ok":True})

@app.get("/api/balance")
def api_balance():
    on = request.args.get("on", default="1")
    is_on = on in ("1","true","True","yes","on")
    try:
        _ADA.enable_balance(is_on)
        return jsonify({"ok": True, "on": is_on})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 500

@app.get("/api/height")
def api_height():
    h = request.args.get("h", type=int)
    if h is None:
        return jsonify({"ok": False, "err": "missing h"}), 400
    try:
        _ADA.set_height(h)
        return jsonify({"ok": True, "h": int(h)})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 500

@app.get("/healthz")
def healthz():
    return "ok", 200

if __name__ == "__main__":
    host = os.getenv("WEB_HOST","127.0.0.1")
    port = int(os.getenv("WEB_PORT","8080"))
    app.run(host=host, port=port)
