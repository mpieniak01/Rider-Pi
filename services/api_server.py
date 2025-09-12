#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rider-Pi – API server (router + entrypoint)

- Router mapuje endpointy na moduły z services.api_core.*
- Dodatkowo: lekki proxy:
    * GET  /api/move|/api/stop  -> web_motion_bridge (8081)
    * POST /api/control|/api/cmd -> web_motion_bridge (8081)/control
"""

from __future__ import annotations
import os
import json
import urllib.parse
import urllib.request
from typing import Dict, Any, Optional, Tuple

from flask import Flask, request, jsonify, make_response, Response, send_from_directory
from services.api_core import compat

app: Flask = compat.app
STATUS_API_PORT = int(os.getenv("STATUS_API_PORT") or os.getenv("API_PORT") or compat.STATUS_API_PORT)

# Statyki (HTML/JS/CSS)
import os as _os
BASE_DIR = _os.path.dirname(_os.path.abspath(__file__))
STATIC_WEB_DIR = _os.path.abspath(os.getenv("WEB_DIR") or _os.path.join(_os.path.dirname(BASE_DIR), "web"))

# ── KONFIG MOSTKA RUCHU ──────────────────────────────────────────────────────
MOTION_BRIDGE_URL = os.getenv("MOTION_BRIDGE_URL") or os.getenv("WEB_BRIDGE_URL") or "http://127.0.0.1:8081"

# ── WSPÓLNE ─────────────────────────────────────────────────────────────────
def _corsify(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return resp

def _proxy_get(path: str, qs_dict: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], int]:
    url = f"{MOTION_BRIDGE_URL}{path}"
    if qs_dict:
        url += "?" + urllib.parse.urlencode(qs_dict, doseq=True)
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=2.0) as resp:
        data = resp.read()
        code = resp.status
    body = json.loads(data.decode("utf-8"))
    return body, code

def _proxy_post_json(path: str, payload: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    url = f"{MOTION_BRIDGE_URL}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            raw = resp.read()
            code = resp.status
            ctype = resp.headers.get("Content-Type", "application/json") or "application/json"
    except Exception as e:
        return {"ok": False, "error": f"web bridge unreachable: {e}"}, 502

    try:
        if ctype.startswith("application/json"):
            body = json.loads(raw.decode("utf-8"))
        else:
            body = {"ok": False, "error": "bad content-type from web bridge", "text": raw[:300].decode("utf-8", "ignore")}
    except Exception:
        body = {"ok": False, "error": "bad json from web bridge", "text": raw[:300].decode("utf-8", "ignore")}
    return body, code

# ── ROUTING: HEALTH / STATE / EVENTS / ETC. ──────────────────────────────────
from services.api_core import state_api  # << wzbogacone /state (w core)
from services.api_core import system_info
app.add_url_rule("/healthz",  view_func=compat.healthz)
app.add_url_rule("/health",   view_func=compat.health_alias)
app.add_url_rule("/state",    view_func=state_api.state_route)  # << router tylko deleguje
app.add_url_rule("/sysinfo",  view_func=system_info.sysinfo)
app.add_url_rule("/metrics",  view_func=system_info.metrics)
app.add_url_rule("/events",   view_func=compat.events)
app.add_url_rule("/livez",    view_func=compat.livez)
app.add_url_rule("/readyz",   view_func=compat.readyz)

# camera & snapshots
from services.api_core import camera
app.add_url_rule("/camera/raw",         view_func=camera.camera_raw,         methods=["GET","HEAD"])
app.add_url_rule("/camera/proc",        view_func=camera.camera_proc,        methods=["GET","HEAD"])
app.add_url_rule("/camera/last",        view_func=camera.camera_last,        methods=["GET","HEAD"])
app.add_url_rule("/camera/placeholder", view_func=camera.camera_placeholder, methods=["GET","HEAD"])
app.add_url_rule("/snapshots/<path:fname>", view_func=camera.snapshots_static)

# services (systemd)
from services.api_core import services_api
app.add_url_rule("/svc",               view_func=services_api.svc_list,   methods=["GET"])
app.add_url_rule("/svc/<name>/status", view_func=services_api.svc_status, methods=["GET"])
app.add_url_rule("/svc/<name>",        view_func=services_api.svc_action, methods=["POST"])

# dashboard (strona)
def serve_control():
    return send_from_directory(STATIC_WEB_DIR, "control.html")
def serve_web(fname):
    return send_from_directory(STATIC_WEB_DIR, fname)
# app.add_url_rule("/control", view_func=serve_control, methods=["GET"])  # opcjonalnie "goły" plik
app.add_url_rule("/web/<path:fname>", view_func=serve_web, methods=["GET"])

from services.api_core import dashboard
app.add_url_rule("/",        view_func=dashboard.dashboard)
app.add_url_rule("/control", view_func=dashboard.control_page)

# ── Vision API: blueprint (w core) ───────────────────────────────────────────
try:
    from services.api_core import vision_api
    vision_bp = getattr(vision_api, "vision_bp", None)
    if vision_bp is None:
        raise ImportError("vision_bp missing")
    app.register_blueprint(vision_bp, url_prefix="/vision")
    app.logger.info("Vision API registered at /vision")
except Exception as e:
    app.logger.warning(f"Vision blueprint not available: {e}")

# ── Control API (proxy) ─────────────────────────────────────────────────────
def control_proxy_core():
    data = request.get_json(force=False, silent=True) or {}
    cmd = (str(data.get("cmd") or data.get("action") or "")).lower().strip()
    if "direction" in data and "dir" not in data:
        data["dir"] = data["direction"]
    if not cmd and "dir" in data:
        cmd = "move"

    if cmd == "move":
        qs = {k: data[k] for k in ("dir","v","t","w") if k in data}
        if "dir" not in qs:
            return {"ok": False, "error": "missing 'dir' for move"}, 400
        return _proxy_get("/api/move", qs)

    if cmd == "stop" or data.get("stop") is True:
        return _proxy_get("/api/stop", None)

    body, code = _proxy_post_json("/api/control", data)
    if code == 404:
        body, code = _proxy_post_json("/control", data)
    return body, code

def control_proxy_handler():
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))
    try:
        body, code = control_proxy_core()
        return _corsify(jsonify(body)), code
    except Exception as e:
        return _corsify(jsonify({"ok": False, "error": f"proxy_control_failed: {e}"})), 502

# GET fallbacki dla starego frontu
def proxy_move_get():
    try:
        body, code = _proxy_get("/api/move", request.args.to_dict(flat=False))
    except Exception as e:
        body, code = {"ok": False, "err": f"proxy_move_failed: {e}"}, 502
    return jsonify(body), code
def proxy_stop_get():
    try:
        body, code = _proxy_get("/api/stop", None)
    except Exception as e:
        body, code = {"ok": False, "err": f"proxy_stop_failed: {e}"}, 502
    return jsonify(body), code

app.add_url_rule("/api/move", view_func=proxy_move_get, methods=["GET"])
app.add_url_rule("/api/stop", view_func=proxy_stop_get, methods=["GET"])
app.add_url_rule("/api/control", view_func=control_proxy_handler, methods=["POST","OPTIONS"])
app.add_url_rule("/api/cmd",     view_func=control_proxy_handler, methods=["POST","OPTIONS"])

# Legacy POST-y (jeśli jeszcze używasz)
from services.api_core import control_api
app.add_url_rule("/api/move",    view_func=control_api.api_move,    methods=["POST"])
app.add_url_rule("/api/stop",    view_func=control_api.api_stop,    methods=["POST"])
app.add_url_rule("/api/preset",  view_func=control_api.api_preset,  methods=["POST"])
app.add_url_rule("/api/voice",   view_func=control_api.api_voice,   methods=["POST"])

# ── BOOTSTRAP ────────────────────────────────────────────────────────────────
def main():
    compat.start_bus_sub()
    compat.start_xgo_ro()
    app.run(host="0.0.0.0", port=STATUS_API_PORT, threaded=True)

if __name__ == "__main__":
    main()
