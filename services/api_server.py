#!/usr/bin/env python3
"""
Rider-Pi – API server (router + entrypoint)

- Router mapuje endpointy na moduły z services.api_core.*
- Dodatkowo: lekki proxy:
    * GET  /api/move|/api/stop  -> web_motion_bridge (8081)
    * POST /api/control|/api/cmd -> web_motion_bridge (8081)/control
"""

from __future__ import annotations

import os

from flask import Flask, send_from_directory

from services.api_core import (
    camera,
    compat,
    control_api,
    control_proxy,
    dashboard,
    services_api,
    state_api,
    system_info,
)

app: Flask = compat.app
STATUS_API_PORT = int(os.getenv("STATUS_API_PORT") or os.getenv("API_PORT") or compat.STATUS_API_PORT)

# Statyki (HTML/JS/CSS)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_WEB_DIR = os.path.abspath(os.getenv("WEB_DIR") or os.path.join(os.path.dirname(BASE_DIR), "web"))

# ── ROUTING: HEALTH / STATE / EVENTS / ETC. ──────────────────────────────────
app.add_url_rule("/healthz", view_func=compat.healthz)
app.add_url_rule("/health", view_func=compat.health_alias)
app.add_url_rule("/state", view_func=state_api.state_route)
app.add_url_rule("/sysinfo", view_func=system_info.sysinfo)
app.add_url_rule("/metrics", view_func=system_info.metrics)
app.add_url_rule("/events", view_func=compat.events)
app.add_url_rule("/livez", view_func=compat.livez)
app.add_url_rule("/readyz", view_func=compat.readyz)

# camera & snapshots
app.add_url_rule("/camera/raw", view_func=camera.camera_raw, methods=["GET", "HEAD"])
app.add_url_rule("/camera/proc", view_func=camera.camera_proc, methods=["GET", "HEAD"])
app.add_url_rule("/camera/last", view_func=camera.camera_last, methods=["GET", "HEAD"])
app.add_url_rule(
    "/camera/placeholder",
    view_func=camera.camera_placeholder,
    methods=["GET", "HEAD"],
)
app.add_url_rule("/snapshots/<path:fname>", view_func=camera.snapshots_static)

# services (systemd)
app.add_url_rule("/svc", view_func=services_api.svc_list, methods=["GET"])
app.add_url_rule("/svc/<name>/status", view_func=services_api.svc_status, methods=["GET"])
app.add_url_rule("/svc/<name>", view_func=services_api.svc_action, methods=["POST"])

# dashboard (strona)
def serve_control() -> object:
    return send_from_directory(STATIC_WEB_DIR, "control.html")


def serve_web(fname):
    return send_from_directory(STATIC_WEB_DIR, fname)


# app.add_url_rule("/control", view_func=serve_control, methods=["GET"])  # opcjonalnie "goły" plik
app.add_url_rule("/web/<path:fname>", view_func=serve_web, methods=["GET"])

app.add_url_rule("/", view_func=dashboard.dashboard)
app.add_url_rule("/control", view_func=dashboard.control_page)

# ── Vision API: blueprint (w core) ───────────────────────────────────────────
try:
    from services.api_core import vision_api

    vision_bp = getattr(vision_api, "vision_bp", None)
    if vision_bp is None:
        raise ImportError("vision_bp missing")
    app.register_blueprint(vision_bp, url_prefix="/vision")
    app.logger.info("Vision API registered at /vision")
except Exception as e:  # pragma: no cover - optional dependency
    app.logger.warning(f"Vision blueprint not available: {e}")

# ── Control API (proxy) ─────────────────────────────────────────────────────
app.add_url_rule("/api/move", view_func=control_proxy.proxy_move_get, methods=["GET"])
app.add_url_rule("/api/stop", view_func=control_proxy.proxy_stop_get, methods=["GET"])
app.add_url_rule(
    "/api/control",
    view_func=control_proxy.control_proxy_handler,
    methods=["POST", "OPTIONS"],
)
app.add_url_rule(
    "/api/cmd",
    view_func=control_proxy.control_proxy_handler,
    methods=["POST", "OPTIONS"],
)

# Legacy POST-y (jeśli jeszcze używasz)
app.add_url_rule("/api/move", view_func=control_api.api_move, methods=["POST"])
app.add_url_rule("/api/stop", view_func=control_api.api_stop, methods=["POST"])
app.add_url_rule("/api/preset", view_func=control_api.api_preset, methods=["POST"])
app.add_url_rule("/api/voice", view_func=control_api.api_voice, methods=["POST"])

# ── BOOTSTRAP ────────────────────────────────────────────────────────────────
def main():
    compat.start_bus_sub()
    compat.start_xgo_ro()
    app.run(host="0.0.0.0", port=STATUS_API_PORT, threaded=True)

if __name__ == "__main__":
    main()
