# services/api_server.py
from __future__ import annotations

import os
from flask import Flask, jsonify, request, make_response, send_from_directory

# --- preferuj istniejący app/konfigurację z compat ---
try:
    import services.api_core.compat as compat
    app: Flask = getattr(compat, "app", Flask(__name__))
    DEFAULT_PORT = int(os.getenv("STATUS_API_PORT") or os.getenv("API_PORT") or getattr(compat, "STATUS_API_PORT", 5000))
except Exception:
    compat = None  # type: ignore
    app = Flask(__name__)
    DEFAULT_PORT = int(os.getenv("STATUS_API_PORT", "5000"))

# --- importy modułów rdzeniowych (routing poniżej) ---
import services.api_core.services_api as services_api
import services.api_core.dashboard as dashboard
import services.api_core.camera as camera
import services.api_core.voice_proxy as voice_proxy
import services.api_core.control_proxy as control_proxy
import services.api_core.system_info as system_info
import services.api_core.state_api as state_api
# Chat: użyjemy „glue” na końcu, żeby rejestrować idempotentnie
import services.api_core.chat_api as chat_api  # noqa: F401
import services.api_core.chat_glue as chat_glue  # dla nowego glue
# Face (nowa ścieżka + legacy shim)
from services.api_core.face_api import render_face as face_render_shim

# ── CORS global (dla dashboardu na 8080 i API na 5000) ───────────────────────
@app.after_request
def _cors_all(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return resp

def _corsify(resp):
    return _cors_all(resp)

# ── FACE: nowe API ───────────────────────────────────────────────────────────
@app.route("/face/ping", methods=["GET"])
def face_ping():
    return jsonify({"ok": True})

@app.route("/face/render", methods=["POST"])
def face_render():
    payload = request.get_json(force=True, silent=True) or {}
    res = face_render_shim(payload)
    status = 503 if (not res.get("ok") and res.get("status") == 503) else 200
    return jsonify(res), status

# ── FACE: legacy /api/draw/face (kompat) ─────────────────────────────────────
@app.route("/api/draw/face", methods=["POST", "OPTIONS"])
def api_draw_face_legacy():
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))
    payload = request.get_json(force=True, silent=True) or {}
    from services.api_core.face_api import draw_face  # zwraca (body, status)
    body, status = draw_face(payload)
    return _corsify(make_response(jsonify(body), status))

# ── ROUTING: HEALTH / STATE / SYSINFO / METRICS / EVENTS / PROBES ───────────
_rules = {r.rule for r in app.url_map.iter_rules()}

def _add_rule(rule, **kw):
    if rule not in _rules:
        app.add_url_rule(rule, **kw)
        _rules.add(rule)

# health/state/sysinfo/metrics/events/livez/readyz
if compat:
    _add_rule("/healthz", view_func=compat.healthz)
    _add_rule("/health", view_func=compat.health_alias)
    _add_rule("/events", view_func=compat.events)
    _add_rule("/livez", view_func=compat.livez)
    _add_rule("/readyz", view_func=compat.readyz)
_add_rule("/state", view_func=state_api.state_route)
_add_rule("/sysinfo", view_func=system_info.sysinfo)
_add_rule("/metrics", view_func=system_info.metrics)

# camera & snapshots
_add_rule("/camera/raw", view_func=camera.camera_raw, methods=["GET", "HEAD"])
_add_rule("/camera/proc", view_func=camera.camera_proc, methods=["GET", "HEAD"])
_add_rule("/camera/last", view_func=camera.camera_last, methods=["GET", "HEAD"])
_add_rule("/camera/placeholder", view_func=camera.camera_placeholder, methods=["GET", "HEAD"])
_add_rule("/snapshots/<path:fname>", view_func=camera.snapshots_static)

# alias kompatybilności z frontem
def _api_last_frame():
    return camera.camera_last()
_add_rule("/api/last_frame", view_func=_api_last_frame, methods=["GET", "HEAD"])

# services (systemd)
_add_rule("/svc", view_func=services_api.svc_list, methods=["GET"])
_add_rule("/svc/<name>/status", view_func=services_api.svc_status, methods=["GET"])
_add_rule("/svc/<name>", view_func=services_api.svc_action, methods=["POST"])

# vision (blueprint opcjonalny)
try:
    from services.api_core import vision_api
    vision_bp = getattr(vision_api, "vision_bp", None)
    if vision_bp:
        app.register_blueprint(vision_bp, url_prefix="/vision")
        app.logger.info("Vision API registered at /vision")
except Exception as e:
    app.logger.warning(f"Vision blueprint not available: {e}")

# control proxy
_add_rule("/api/control", view_func=control_proxy.control_proxy_handler, methods=["POST", "OPTIONS"])
_add_rule("/api/cmd", view_func=control_proxy.control_proxy_handler, methods=["POST", "OPTIONS"])

# voice proxy
_add_rule("/api/voice/capture", view_func=voice_proxy.capture_handler, methods=["POST", "OPTIONS"])
_add_rule("/api/voice/say", view_func=voice_proxy.say_handler, methods=["POST", "OPTIONS"])

# ── Chat API: rejestracja „glue” idempotentnie ───────────────────────────────
try:
    chat_glue.register(app)  # doda /api/chat/history, /api/chat/send
    app.logger.info("Chat API registered at /api/chat/*")
except Exception as e:
    app.logger.warning(f"Chat API not available: {e}")

# ── Dashboard / pliki statyczne ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_WEB_DIR = os.path.abspath(os.getenv("WEB_DIR") or os.path.join(os.path.dirname(BASE_DIR), "web"))

def serve_web(fname):
    return send_from_directory(STATIC_WEB_DIR, fname)

# root i control page (jeśli dashboard je dostarcza)
_add_rule("/web/<path:fname>", view_func=serve_web, methods=["GET"])
_add_rule("/", view_func=dashboard.dashboard, methods=["GET"])
_add_rule("/control", view_func=dashboard.control_page, methods=["GET"])

# ── BOOTSTRAP ────────────────────────────────────────────────────────────────
def main():
    try:
        if compat:
            compat.start_bus_sub()
            compat.start_xgo_ro()
    except Exception as e:
        app.logger.warning(f"compat init warning: {e}")
    port = DEFAULT_PORT
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    main()
