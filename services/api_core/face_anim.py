# services/api_core/face_anim.py
from time import time
from flask import request, jsonify, make_response

# Prosty stan w pamięci (wystarczy na MVP)
STATE = {
    "playing": False,
    "expr": "neutral",
    "fps": 20,
    "running": False,    # alias na potrzeby UI
    "started_ts": None,
    "last_ts": None,
}

ALLOWED = {"neutral", "happy", "sad", "blink"}

def _corsify(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return resp

def _norm_expr(v):
    v = str(v or "neutral").lower().strip()
    return v if v in ALLOWED else "neutral"

def post_play():
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))
    p = request.get_json(silent=True) or {}
    STATE["expr"] = _norm_expr(p.get("expr"))
    try:
        STATE["fps"] = int(p.get("fps", 20))
    except Exception:
        STATE["fps"] = 20
    STATE["playing"] = True
    STATE["running"] = True
    STATE["started_ts"] = time()
    STATE["last_ts"] = STATE["started_ts"]
    return _corsify(jsonify({"ok": True, "state": STATE})), 200

def post_stop():
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))
    STATE["playing"] = False
    STATE["running"] = False
    STATE["last_ts"] = time()
    return _corsify(jsonify({"ok": True, "state": STATE})), 200

def get_state():
    # bez preflight – GET
    return _corsify(jsonify({"ok": True, "state": STATE})), 200
