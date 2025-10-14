from __future__ import annotations

import os

from flask import Flask, jsonify, make_response, request, send_from_directory

# --- preferuj istniejący app/konfigurację z compat ---
try:
    import services.api_core.compat as compat

    app: Flask = getattr(compat, "app", Flask(__name__))
    DEFAULT_PORT = int(
        os.getenv("STATUS_API_PORT") or os.getenv("API_PORT") or getattr(compat, "STATUS_API_PORT", 5000)
    )
except Exception:
    compat = None  # type: ignore
    app = Flask(__name__)
    DEFAULT_PORT = int(os.getenv("STATUS_API_PORT", "5000"))

# --- importy modułów rdzeniowych (routing poniżej) ---
import services.api_core.camera as camera

# Chat/glue
import services.api_core.chat_api as chat_api  # noqa: F401
import services.api_core.control_proxy as control_proxy
import services.api_core.dashboard as dashboard
import services.api_core.face_anim as face_anim
import services.api_core.services_api as services_api  # właściwy moduł usług
import services.api_core.state_api as state_api
import services.api_core.system_info as system_info
import services.api_core.voice_proxy as voice_proxy
from services.api_core.face_api import render_face as face_render_shim


# ── CORS global ──────────────────────────────────────────────────────────────
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


# ── FACE: animacja ───────────────────────────────────────────────────────────
@app.route("/face/play", methods=["POST", "OPTIONS"])
def face_play():
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))
    payload = request.get_json(silent=True) or {}
    res = face_anim.play(payload)
    return _corsify(jsonify(res)), 200


@app.route("/face/stop", methods=["POST", "OPTIONS"])
def face_stop():
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))
    payload = request.get_json(silent=True) or {}
    res = face_anim.stop(payload)
    return _corsify(jsonify(res)), 200


@app.route("/face/state", methods=["GET"])
def face_state():
    res = face_anim.get_state()
    return _corsify(jsonify(res)), 200


# ── FACE: legacy ─────────────────────────────────────────────────────────────
@app.route("/api/draw/face", methods=["POST", "OPTIONS"])
def api_draw_face_legacy():
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))
    payload = request.get_json(force=True, silent=True) or {}
    from services.api_core.face_api import draw_face  # zwraca (body, status)

    body, status = draw_face(payload)
    return _corsify(jsonify(body)), status


# ── ROUTING ──────────────────────────────────────────────────────────────────
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


# alias dla frontu
def _api_last_frame():
    return camera.camera_last()


_add_rule("/api/last_frame", view_func=_api_last_frame, methods=["GET", "HEAD"])


# ── SERVICES (systemd) ──────────────────────────────────────────────────────
# Jedna trasa, dwie metody → NIE używamy helpera (żeby nie pominął POST).
@app.route("/svc", methods=["GET"])
def svc_list_route():
    return services_api.svc_list()


@app.route("/svc/<name>", methods=["GET", "POST"])
def svc_name_route(name: str):
    if request.method == "GET":
        return services_api.svc_status(name)
    # POST = akcja
    return services_api.svc_action(name)


# Alias zgodności
_add_rule("/svc/<name>/status", view_func=services_api.svc_status, methods=["GET"])

# (UWAGA) Rejestracja vision blueprint odbywa się w sekcji BOOTSTRAP przez lazy-import.

# control proxy
_add_rule("/api/control", view_func=control_proxy.control_proxy_handler, methods=["POST", "OPTIONS"])
_add_rule("/api/cmd", view_func=control_proxy.control_proxy_handler, methods=["POST", "OPTIONS"])

# voice proxy
_add_rule("/api/voice/capture", view_func=voice_proxy.capture_handler, methods=["POST", "OPTIONS"])
_add_rule("/api/voice/say", view_func=voice_proxy.say_handler, methods=["POST", "OPTIONS"])


# bus health (stub)
@app.route("/api/bus/health", methods=["GET", "OPTIONS"])
def _bus_health():
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))
    return _corsify(jsonify({"ok": True})), 200


# ── Static / dashboard ───────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_WEB_DIR = os.path.abspath(os.getenv("WEB_DIR") or os.path.join(os.path.dirname(BASE_DIR), "web"))


def serve_web(fname):
    return send_from_directory(STATIC_WEB_DIR, fname)


_add_rule("/web/<path:fname>", view_func=serve_web, methods=["GET"])
_add_rule("/", view_func=dashboard.dashboard, methods=["GET"])
_add_rule("/control", view_func=dashboard.control_page, methods=["GET"])


# ── Local control fallback (przed startem serwera) ───────────────────────────
def _register_local_control_fallback():
    try:
        _has_bridge = bool(os.getenv("WEB_BRIDGE_URL", "").strip())
    except Exception:
        _has_bridge = False

    rules_now = {r.rule for r in app.url_map.iter_rules()}
    need_local = (not _has_bridge) and ("/api/control" not in rules_now)

    if not need_local:
        return

    try:
        import json as _json

        from flask import jsonify as _jsonify, make_response as _mk, request as _req

        try:
            import zmq  # type: ignore

            _ctx = zmq.Context.instance()
            _bus_addr = os.getenv("BUS_PUB_ADDR") or f"tcp://127.0.0.1:{os.getenv('BUS_PUB_PORT', '5555')}"
            _pub = _ctx.socket(zmq.PUB)
            _pub.connect(_bus_addr)
            _PUBLISH = True
        except Exception as _e:
            _PUBLISH = False
            app.logger.warning(f"[control-local] pyzmq not available or BUS connect failed: {_e}")

        def _control_local():
            if _req.method == "OPTIONS":
                return _corsify(_mk("", 204))
            payload = _req.get_json(silent=True) or {}
            if "cmd" not in payload:
                payload = {"cmd": "move", "dir": payload.get("dir", "stop")}
            info = {"ok": True, "mode": "local", "published": False}
            if _PUBLISH:
                try:
                    topic = "motion.cmd"
                    _pub.send_string(f"{topic} {_json.dumps(payload)}")
                    info["published"] = True
                except Exception as e:
                    info.update(ok=False, error=f"bus_publish_failed: {e}")
            return _corsify(_jsonify(info)), 200 if info.get("ok") else 500

        app.add_url_rule("/api/control", view_func=_control_local, methods=["POST", "OPTIONS"])
        app.add_url_rule("/api/cmd", view_func=_control_local, methods=["POST", "OPTIONS"])
        app.logger.info("[control-local] registered /api/control,/api/cmd (no WEB_BRIDGE_URL)")
    except Exception as e:
        app.logger.warning(f"[control-local] fallback not active: {e}")


_register_local_control_fallback()


# ── BOOTSTRAP ────────────────────────────────────────────────────────────────

# --- [Rider-Pi] register vision_api blueprint(s) ---
try:
    import importlib

    _va = importlib.import_module("services.api_core.vision_api")
    _bp = getattr(_va, "bp", None)
    if _bp is None:
        raise RuntimeError("vision_api.bp missing (circular import?)")
    app.register_blueprint(_bp)  # /vision/*
    app.register_blueprint(_bp, url_prefix="/api")  # /api/vision/*
    app.logger.info("[api] vision_api blueprints registered: /vision/* and /api/vision/*")
except Exception as e:
    app.logger.exception("[api] failed to register vision_api blueprint: %s", e)


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
