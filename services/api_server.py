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
from typing import Dict, Any, Optional

from flask import Flask, request, jsonify, make_response, Response, send_from_directory

# Główny rdzeń stanu + /healthz|/state|/sysinfo|/metrics|/events
from services.api_core import compat

app: Flask = compat.app
STATUS_API_PORT = int(os.getenv("STATUS_API_PORT") or os.getenv("API_PORT") or compat.STATUS_API_PORT)
# Katalog ze statycznym webem (czyste HTML/JS/CSS)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_WEB_DIR = os.path.abspath(os.getenv("WEB_DIR") or os.path.join(os.path.dirname(BASE_DIR), "web"))


# ── KONFIG MOSTKA RUCHU ──────────────────────────────────────────────────────
MOTION_BRIDGE_URL = os.getenv("MOTION_BRIDGE_URL", "http://127.0.0.1:8081")

# ── PROSTE PROXY DO MOSTKA (bez zewn. zależności) ───────────────────────────
def _proxy_get(path: str, qs_dict: Optional[Dict[str, Any]] = None):
    """GET -> web_motion_bridge, zwraca zdekodowany JSON i kod HTTP."""
    url = f"{MOTION_BRIDGE_URL}{path}"
    if qs_dict:
        url += "?" + urllib.parse.urlencode(qs_dict, doseq=True)
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=2.0) as resp:
        data = resp.read()
        code = resp.status
    body = json.loads(data.decode("utf-8"))
    return body, code

def _proxy_post_json(path: str, payload: Dict[str, Any]):
    """POST JSON -> web_motion_bridge, zwraca zdekodowany JSON i kod HTTP."""
    url = f"{MOTION_BRIDGE_URL}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            raw = resp.read()
            code = resp.status
            ctype = resp.headers.get("Content-Type", "application/json")
    except Exception as e:
        # Błąd transportu do mostka
        return {"ok": False, "error": f"web bridge unreachable: {e}"}, 502

    # Spróbuj parsować JSON, ale nie panikuj gdy text:
    try:
        if ctype.startswith("application/json"):
            body = json.loads(raw.decode("utf-8"))
        else:
            body = {"ok": False, "error": "bad content-type from web bridge", "text": raw[:300].decode("utf-8", "ignore")}
    except Exception:
        body = {"ok": False, "error": "bad json from web bridge", "text": raw[:300].decode("utf-8", "ignore")}
    return body, code

def _corsify(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return resp

# ── ROUTING: HEALTH / STATE / EVENTS / ETC. ──────────────────────────────────
app.add_url_rule("/healthz",  view_func=compat.healthz)
app.add_url_rule("/health",   view_func=compat.health_alias)
app.add_url_rule("/state",    view_func=compat.state)
app.add_url_rule("/sysinfo",  view_func=compat.sysinfo)
app.add_url_rule("/metrics",  view_func=compat.metrics)
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
    # /control -> web/control.html (Wasz czysty plik HTML)
    return send_from_directory(STATIC_WEB_DIR, "control.html")

def serve_web(fname):
    # /web/<asset> -> dowolne zasoby z katalogu web/ (JS/CSS/obrazy)
    return send_from_directory(STATIC_WEB_DIR, fname)

# Rejestracja tras statycznych
#app.add_url_rule("/control", view_func=serve_control, methods=["GET"])
app.add_url_rule("/web/<path:fname>", view_func=serve_web, methods=["GET"])

from services.api_core import dashboard
app.add_url_rule("/",        view_func=dashboard.dashboard)
app.add_url_rule("/control", view_func=dashboard.control_page)  # GET (strona)

# control API (komendy – stary mechanizm dla części endpointów)
from services.api_core import control_api
app.add_url_rule("/api/move",    view_func=control_api.api_move,    methods=["POST"])
app.add_url_rule("/api/stop",    view_func=control_api.api_stop,    methods=["POST"])
app.add_url_rule("/api/preset",  view_func=control_api.api_preset,  methods=["POST"])
app.add_url_rule("/api/voice",   view_func=control_api.api_voice,   methods=["POST"])
# UWAGA: /api/cmd NIE kierujemy do control_api – będzie proxowane do mostka.

# GET -> proxy do mostka (kompatybilność starego frontu)
def proxy_move_get():
    try:
        body, code = _proxy_get("/api/move", request.args.to_dict(flat=False))
    except Exception as e:
        body, code = {"ok": False, "err": f"proxy_move_failed: {e}"}, 502
    return jsonify(body), code
app.add_url_rule("/api/move", view_func=proxy_move_get, methods=["GET"])

def proxy_stop_get():
    try:
        body, code = _proxy_get("/api/stop", None)
    except Exception as e:
        body, code = {"ok": False, "err": f"proxy_stop_failed: {e}"}, 502
    return jsonify(body), code
app.add_url_rule("/api/stop", view_func=proxy_stop_get, methods=["GET"])

# POST -> jednolite proxy do mostka /control
def _proxy_control_from_body():
    # Parsuj JSON bezpiecznie i toleruj puste ciało
    data = request.get_json(force=False, silent=True) or {}

    # Aliasy i normalizacja
    cmd = (str(data.get("cmd") or data.get("action") or "").lower()).strip()
    if "direction" in data and "dir" not in data:
        data["dir"] = data["direction"]
    if not cmd and "dir" in data:
        cmd = "move"

    # --- Mapowanie deterministyczne ---
    if cmd == "move":
        qs = {}
        for k in ("dir","v","t","w"):  # w=omega (opcjonalnie)
            if k in data:
                qs[k] = data[k]
        if "dir" not in qs:
            return _corsify(jsonify({"ok": False, "error": "missing 'dir' for move"})), 400
        body, code = _proxy_get("/api/move", qs)
        return _corsify(jsonify(body)), code

    if cmd == "stop" or data.get("stop") is True:
        body, code = _proxy_get("/api/stop", None)
        return _corsify(jsonify(body)), code

    # Fallback: przekaż jako POST do web-bridge (kompat)
    body, code = _proxy_post_json("/api/control", data)
    if code == 404:
        body, code = _proxy_post_json("/control", data)
    resp = jsonify(body)
    return _corsify(resp), code


def api_control_proxy():
    from flask import request, jsonify, make_response
    import os, json, urllib.parse, urllib.request

    def _corsify(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        return resp

    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))

    data = request.get_json(silent=True) or {}
    cmd = (str(data.get("cmd") or data.get("action") or "")).lower().strip()
    if "direction" in data and "dir" not in data:
        data["dir"] = data["direction"]
    if not cmd and "dir" in data:
        cmd = "move"

    base = os.getenv("MOTION_BRIDGE_URL") or os.getenv("WEB_BRIDGE_URL") or "http://127.0.0.1:8081"

    def _get_json(url):
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2.0) as r:
            body = json.loads(r.read().decode("utf-8"))
            return body, r.status

    def _post_json(path, payload):
        url = f"{base}{path}"
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data_bytes, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=2.0) as r:
            raw = r.read(); code = r.status
            ctype = r.headers.get("Content-Type","application/json")
        try:
            body = json.loads(raw.decode("utf-8")) if ctype.startswith("application/json") else {
                "ok": False, "error": "bad content-type from web bridge", "text": raw[:300].decode("utf-8","ignore")
            }
        except Exception:
            body = {"ok": False, "error": "bad json from web bridge", "text": raw[:300].decode("utf-8","ignore")}
        return body, code

    try:
        # --- mapowanie deterministyczne ---
        if cmd == "stop" or data.get("stop") is True:
            body, code = _get_json(f"{base}/api/stop")
            return _corsify(jsonify(body)), code

        if cmd == "move" or "dir" in data:
            qs = {k: data[k] for k in ("dir","v","t","w") if k in data}
            if "dir" not in qs:
                return _corsify(jsonify({"ok": False, "error": "missing 'dir' for move"})), 400
            url = f"{base}/api/move?" + urllib.parse.urlencode(qs, doseq=True)
            body, code = _get_json(url)
            return _corsify(jsonify(body)), code

        # --- fallback: zgodność wsteczna ---
        try:
            body, code = _post_json("/api/control", data)
        except Exception:
            body, code = _post_json("/control", data)
        return _corsify(jsonify(body)), code

    except Exception as e:
        return _corsify(jsonify({"ok": False, "error": f"proxy_control_failed: {e}"})), 502

app.add_url_rule("/api/control", view_func=api_control_proxy, methods=["POST","OPTIONS"])

def api_cmd_proxy():
    # dashboard / inne klienty mogą wysyłać tu to samo co do /api/control
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))
    return _proxy_control_from_body()
app.add_url_rule("/api/cmd", view_func=api_cmd_proxy, methods=["POST","OPTIONS"])

# pozostałe aliasy/stare ścieżki "api/*"
app.add_url_rule("/api/version",     view_func=compat.api_version)
app.add_url_rule("/api/bus/health",  view_func=compat.api_bus_health)
app.add_url_rule("/api/status",      view_func=compat.api_status)
app.add_url_rule("/api/metrics",     view_func=compat.api_metrics_alias)
app.add_url_rule("/api/devices",     view_func=compat.api_devices)
app.add_url_rule("/api/last_frame",  view_func=compat.api_last_frame)
app.add_url_rule("/api/flags",       view_func=compat.api_flags_get, methods=["GET"])
app.add_url_rule("/api/flags/<path:name>/<state>", view_func=compat.api_flags_set, methods=["POST"])

# ── BOOTSTRAP ────────────────────────────────────────────────────────────────
def main():
    # start pętli BUS i UART (idempotentnie)
    compat.start_bus_sub()
    compat.start_xgo_ro()
    app.run(host="0.0.0.0", port=STATUS_API_PORT, threaded=True)

if __name__ == "__main__":
    main()

