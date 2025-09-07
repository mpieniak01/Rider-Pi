#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import time, json
from flask import Response, request
from . import compat as C

def api_move():
    data = request.get_json(silent=True) or {}
    vx  = float(data.get("vx", 0.0)); vy = float(data.get("vy", 0.0)); yaw = float(data.get("yaw", 0.0))
    duration = float(data.get("duration", 0.0))
    C.bus_pub("cmd.move", {"vx": vx, "vy": vy, "yaw": yaw, "duration": duration, "ts": time.time()})
    return Response('{"ok": true}', mimetype="application/json")

def api_stop():
    C.bus_pub("cmd.stop", {"ts": time.time()})
    return Response('{"ok": true}', mimetype="application/json")

def api_preset():
    name = (request.get_json(silent=True) or {}).get("name")
    C.bus_pub("cmd.preset", {"name": name, "ts": time.time()})
    return Response('{"ok": true}', mimetype="application/json")

def api_voice():
    text = (request.get_json(silent=True) or {}).get("text", "")
    C.bus_pub("cmd.voice", {"text": text, "ts": time.time()})
    return Response('{"ok": true}', mimetype="application/json")

def api_cmd():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return Response('{"error":"JSON object expected"}', mimetype="application/json", status=400)
    t = (data.get("type") or "").lower(); ts = time.time()
    try:
        if t == "drive":
            vx  = float(data.get("lx") or data.get("vx") or 0.0)
            yaw = float(data.get("az") or data.get("yaw") or 0.0)
            dur = float(data.get("dur") or data.get("duration") or 0.0)
            C.bus_pub("cmd.move", {"vx": vx, "yaw": yaw, "duration": dur, "ts": ts}); return Response('{"ok": true}', mimetype="application/json")
        if t == "stop":
            C.bus_pub("cmd.stop", {"ts": ts}); return Response('{"ok": true}', mimetype="application/json")
        if t == "spin":
            dir_ = (data.get("dir") or "").lower()
            speed = float(data.get("speed") or 0.3); dur = float(data.get("dur") or data.get("duration") or 0.45)
            yaw   = -abs(speed) if dir_ == "left" else +abs(speed)
            C.bus_pub("cmd.move", {"vx": 0.0, "yaw": yaw, "duration": dur, "ts": ts}); return Response('{"ok": true}', mimetype="application/json")
        C.bus_pub("cmd.raw", {"payload": data, "ts": ts})
        return Response('{"ok": true, "note": "unknown type -> cmd.raw"}', mimetype="application/json")
    except Exception as e:
        return Response(json.dumps({"error": str(e)}), mimetype="application/json", status=500)

def api_control():
    data = request.get_json(silent=True) or {}
    action = (request.args.get("action") or data.get("action") or "").strip().lower()
    ms = request.args.get("ms") or data.get("ms") or request.args.get("duration") or data.get("duration") or 0
    try: ms = int(ms)
    except Exception: ms = 0

    vx = 0.0; yaw = 0.0
    if action in ("forward", "fwd", "up"):   vx = +0.4
    elif action in ("back", "backward", "down"): vx = -0.4
    elif action in ("left",):   yaw = -0.5
    elif action in ("right",):  yaw = +0.5
    elif action in ("stop", "halt"):
        C.bus_pub("cmd.stop", {"ts": time.time()})
        return Response('{"ok": true, "sent": {"action": "stop"}}', mimetype="application/json")

    if vx == 0.0 and yaw == 0.0 and action not in ("stop",):
        return Response('{"ok": false, "error": "unknown action"}', mimetype="application/json", status=400)

    C.bus_pub("cmd.move", {"vx": vx, "yaw": yaw, "duration": ms/1000.0, "ts": time.time()})
    return Response(json.dumps({"ok": True, "sent": {"action": action, "vx": vx, "yaw": yaw, "ms": ms}}), mimetype="application/json")
