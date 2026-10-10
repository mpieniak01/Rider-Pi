# services/api_server.py
from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from flask import (
    Flask,
    Response,
    jsonify,
    make_response,
    request,
)

# --- preferuj istniejący app/konfigurację z compat ---
try:
    import services.api_core.compat as compat

    app: Flask = getattr(compat, "app", Flask(__name__))
    DEFAULT_PORT = int(
        os.getenv("STATUS_API_PORT") or os.getenv("API_PORT") or getattr(compat, "STATUS_API_PORT", 8080)
    )
except Exception:
    compat = None  # type: ignore
    app = Flask(__name__)
    DEFAULT_PORT = int(os.getenv("STATUS_API_PORT", "8080"))

# --- importy modułów rdzeniowych (routing poniżej) ---
import services.api_core.ai_mode_api as ai_mode_api
import services.api_core.camera as camera
import services.api_core.chat_api as chat_api  # noqa: F401
import services.api_core.control_api as control_api
import services.api_core.control_proxy as control_proxy
import services.api_core.dashboard as dashboard
import services.api_core.face_anim as face_anim
import services.api_core.features_api as features_api
import services.api_core.google_home_api as google_home_api
import services.api_core.google_proxy as google_proxy
import services.api_core.models_api as models_api
import services.api_core.navigator_api as navigator_api
import services.api_core.provider_api as provider_api
import services.api_core.services_api as services_api
import services.api_core.state_api as state_api
import services.api_core.system_info as system_info
import services.api_core.version_api as version_api
import services.api_core.voice_local_proxy as voice_local_proxy
import services.api_core.voice_proxy as voice_proxy
import services.odometry_api as odometry_api
from services.api_core.api_metrics import _update_api_metrics
from services.api_core.chat_routes import register_chat_endpoints
from services.api_core.face_api import render_face as face_render_shim
from services.api_core.home_auth_route import home_auth as home_auth_flow, home_auth_url as home_auth_request
from services.api_core.resource_api import api_resource
from services.api_core.service_logs import service_logs
from services.api_core.static_pages import serve_chat, serve_google_home, serve_home, serve_navigation, serve_web

# ── Metryki API helper ───────────────────────────────────────────────────────


# ── CORS global + metryki ────────────────────────────────────────────────────
@app.after_request
def _cors_all(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS,HEAD"

    # Zliczanie metryk dla interaktywnych endpointów (pomijamy system/monitorowanie)
    if compat:
        _update_api_metrics(request.path, resp.status_code)

    return resp


def _corsify(resp: Response) -> Response:
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


app.add_url_rule("/api/resource/<name>", view_func=api_resource, methods=["GET", "POST", "OPTIONS"])


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


def _add_rule(rule: str, **kw: Any) -> None:
    """Dodaje trasę tylko jeśli jeszcze nie istnieje (idempotentnie)."""
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
    _add_rule("/api/flags", view_func=compat.api_flags_get, methods=["GET"])
    _add_rule(
        "/api/flags/<name>/<state>",
        view_func=compat.api_flags_set,
        methods=["POST"],
    )
_add_rule("/state", view_func=state_api.state_route)
_add_rule("/sysinfo", view_func=system_info.sysinfo)
_add_rule("/metrics", view_func=system_info.metrics)

# camera & snapshots
_add_rule("/camera/raw", view_func=camera.camera_raw, methods=["GET", "HEAD"])
_add_rule("/camera/proc", view_func=camera.camera_proc, methods=["GET", "HEAD"])
_add_rule("/camera/last", view_func=camera.camera_last, methods=["GET", "HEAD"])
_add_rule("/camera/placeholder", view_func=camera.camera_placeholder, methods=["GET", "HEAD"])
_add_rule("/snapshots/<path:fname>", view_func=camera.snapshots_static)


def _api_last_frame():
    return camera.camera_last()


_add_rule("/api/last_frame", view_func=_api_last_frame, methods=["GET", "HEAD"])

# AI mode control
_add_rule(
    "/api/system/ai-mode",
    view_func=ai_mode_api.ai_mode_handler,
    methods=["GET", "PUT", "POST", "OPTIONS"],
)

# Provider registry
_add_rule(
    "/api/providers/state",
    view_func=provider_api.providers_state_handler,
    methods=["GET", "OPTIONS"],
)
_add_rule(
    "/api/providers/health",
    view_func=provider_api.providers_health_handler,
    methods=["GET", "OPTIONS"],
)
_add_rule(
    "/api/providers/pc-heartbeat",
    view_func=provider_api.providers_pc_heartbeat_handler,
    methods=["POST", "OPTIONS"],
)
_add_rule(
    "/api/providers/<domain>",
    view_func=provider_api.provider_domain_handler,
    methods=["GET", "PATCH", "OPTIONS"],
)

# Model inventory
_add_rule(
    "/api/models/installed",
    view_func=models_api.installed_models_handler,
    methods=["GET", "OPTIONS"],
)


# ── SERVICES (systemd) ──────────────────────────────────────────────────────
@app.route("/svc", methods=["GET"])
def svc_list_route():
    return services_api.svc_list()


@app.route("/svc/<name>", methods=["GET", "POST"])
def svc_name_route(name: str):
    if request.method == "GET":
        return services_api.svc_status(name)
    return services_api.svc_action(name)


_add_rule("/svc/<name>/status", view_func=services_api.svc_status, methods=["GET"])
_add_rule("/api/services/<unit>/logs", view_func=service_logs, methods=["GET"])

# control proxy
_add_rule(
    "/api/control",
    view_func=control_proxy.control_proxy_handler,
    methods=["POST", "OPTIONS"],
)
_add_rule(
    "/api/cmd",
    view_func=control_proxy.control_proxy_handler,
    methods=["POST", "OPTIONS"],
)

# control API - balance and height
_add_rule("/api/safety", view_func=control_api.api_safety, methods=["GET", "POST", "OPTIONS"])
_add_rule("/api/odometry/state", view_func=odometry_api.reference_state, methods=["GET"])
_add_rule("/api/odometry/reference", view_func=odometry_api.operator_reference, methods=["POST"])
_add_rule(
    "/api/control/balance",
    view_func=control_api.api_balance,
    methods=["POST", "OPTIONS"],
)
_add_rule("/api/control/height", view_func=control_api.api_height, methods=["POST", "OPTIONS"])
_add_rule(
    "/api/control/state",
    view_func=control_api.api_control_state,
    methods=["GET", "OPTIONS"],
)
_add_rule(
    "/api/motion/queue",
    view_func=control_api.api_motion_queue,
    methods=["GET", "OPTIONS"],
)

# navigator API (Rekonesans mode)
_add_rule(
    "/api/navigator/start",
    view_func=navigator_api.api_navigator_start,
    methods=["POST", "OPTIONS"],
)
_add_rule(
    "/api/navigator/stop",
    view_func=navigator_api.api_navigator_stop,
    methods=["POST", "OPTIONS"],
)
_add_rule(
    "/api/navigator/config",
    view_func=navigator_api.api_navigator_config,
    methods=["POST", "OPTIONS"],
)
_add_rule(
    "/api/navigator/status",
    view_func=navigator_api.api_navigator_status,
    methods=["GET", "OPTIONS"],
)
_add_rule(
    "/api/navigator/return_home",
    view_func=navigator_api.api_navigator_return_home,
    methods=["POST", "OPTIONS"],
)

# features (core business logic)
_add_rule(
    "/api/logic/catalog",
    view_func=features_api.feature_catalog_handler,
    methods=["GET", "OPTIONS"],
)
_add_rule(
    "/api/logic/features",
    view_func=features_api.feature_registry_handler,
    methods=["GET", "OPTIONS"],
)
_add_rule(
    "/api/logic/summary",
    view_func=features_api.feature_summary_handler,
    methods=["GET", "OPTIONS"],
)
_add_rule(
    "/api/logic/state",
    view_func=features_api.feature_state_handler,
    methods=["GET", "OPTIONS"],
)
_add_rule(
    "/api/logic/feature/<name>",
    view_func=features_api.feature_handler,
    methods=["POST", "OPTIONS"],
)

# voice proxy (zdalne/istniejące)
_add_rule(
    "/api/voice/capture",
    view_func=voice_proxy.capture_handler,
    methods=["POST", "OPTIONS"],
)
_add_rule("/api/voice/say", view_func=voice_proxy.say_handler, methods=["POST", "OPTIONS"])

# voice local proxy
_add_rule(
    "/api/voice/tts",
    view_func=voice_local_proxy.tts_local_handler,
    methods=["POST", "OPTIONS"],
)
_add_rule(
    "/api/voice/asr",
    view_func=voice_local_proxy.asr_local_handler,
    methods=["POST", "OPTIONS"],
)
_add_rule(
    "/api/voice/providers",
    view_func=voice_local_proxy.providers_list_handler,
    methods=["GET", "OPTIONS"],
)
_add_rule(
    "/api/voice/providers/test",
    view_func=voice_local_proxy.providers_test_handler,
    methods=["POST", "OPTIONS"],
)


# ── GOOGLE HOME ──────────────────────────────────────────────────────────────
# Configuration for command caching
DATA_DIR = Path(os.getenv("DATA_DIR", Path.home() / "robot" / "data"))
GOOGLE_DATA_DIR = DATA_DIR / "google"
LAST_COMMAND_FILE = GOOGLE_DATA_DIR / "last_command.json"


def _save_command_cache(device_id: str, command: str, params: dict[str, Any], result: dict[str, Any]) -> None:
    """Save command response to cache file."""
    try:
        GOOGLE_DATA_DIR.mkdir(parents=True, exist_ok=True)
        cache_data = {
            "timestamp": time.time(),
            "device_id": device_id,
            "command": command,
            "params": params,
            "ok": result.get("ok", False),
            "response": result.get("result"),
            "error": result.get("error"),
        }
        LAST_COMMAND_FILE.write_text(json.dumps(cache_data, indent=2))
    except Exception as e:
        app.logger.warning(f"Failed to save command cache to {LAST_COMMAND_FILE}: {e}")


def _auto_refresh_token_and_retry(api_call: Callable[..., dict[str, Any]], *args, **kwargs) -> dict[str, Any]:
    result = api_call(*args, **kwargs)
    if result.get("status_code") == 401:
        if google_home_api.refresh_access_token():
            result = api_call(*args, **kwargs)
    return result


@app.route("/api/home/auth/url", methods=["GET", "OPTIONS"])  # NEW
def home_auth_url():
    return home_auth_request(_corsify, app.logger)


@app.route("/api/home/auth", methods=["POST", "OPTIONS"])
def home_auth():
    return home_auth_flow(_corsify, app.logger)


@app.route("/api/home/status", methods=["GET", "OPTIONS"])
def home_status():
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))
    is_auth = google_home_api.is_authenticated()
    return _corsify(jsonify({"ok": True, "authenticated": is_auth})), 200


@app.route("/api/home/devices", methods=["GET", "OPTIONS"])
def home_devices():
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))
    if not google_home_api.is_authenticated():
        return _corsify(jsonify({"ok": False, "error": "Not authenticated"})), 401
    result = _auto_refresh_token_and_retry(google_home_api.get_devices)
    if result.get("ok"):
        return _corsify(jsonify({"ok": True, "devices": result.get("devices", [])})), 200
    app.logger.error("Failed to get devices: %s", result.get("error", "Unknown error"))
    status_code = 401 if result.get("status_code") == 401 else 500
    error_msg = "Not authenticated" if status_code == 401 else "Failed to retrieve devices"
    return _corsify(jsonify({"ok": False, "error": error_msg})), status_code


@app.route("/api/home/command", methods=["POST", "OPTIONS"])
def home_command():
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))
    if not google_home_api.is_authenticated():
        return _corsify(jsonify({"ok": False, "error": "Not authenticated"})), 401
    payload = request.get_json(silent=True) or {}
    device_id = payload.get("deviceId")
    command = payload.get("command")
    params = payload.get("params", {})
    if not device_id or not command:
        return _corsify(jsonify({"ok": False, "error": "Missing deviceId or command"})), 400
    result = _auto_refresh_token_and_retry(google_home_api.send_command, device_id, command, params)
    _save_command_cache(device_id, command, params, result)
    if result.get("ok"):
        return _corsify(jsonify({"ok": True, "result": result.get("result", {})})), 200
    app.logger.error("Failed to send command: %s", result.get("error", "Unknown error"))
    status_code = 401 if result.get("status_code") == 401 else 500
    error_msg = "Not authenticated" if status_code == 401 else "Command failed"
    return _corsify(jsonify({"ok": False, "error": error_msg})), status_code


# bus health (stub)
@app.route("/api/bus/health", methods=["GET", "OPTIONS"])
def _bus_health():
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))
    return _corsify(jsonify({"ok": True})), 200


# ── API Metrics ──────────────────────────────────────────────────────────────
@app.route("/api/app-metrics", methods=["GET"])
def app_metrics():
    """
    Endpoint zwracający metryki aplikacyjne (OK/Error) dla interaktywnych API.
    Nie wymaga autentykacji, nie jest sam zliczany w metrykach.
    """
    if not compat:
        return jsonify({"ok": True, "metrics": {}, "total_errors": 0}), 200

    # Use dashboard.get_metrics_snapshot() for consistent metrics retrieval
    snapshot = dashboard.get_metrics_snapshot()
    return jsonify(
        {
            "ok": True,
            "metrics": snapshot["metrics"],
            "total_errors": snapshot["total_errors"],
        }
    ), 200


# ── Static / dashboard ───────────────────────────────────────────────────────
_add_rule("/web/<path:fname>", view_func=serve_web, methods=["GET"], strict_slashes=False)
_add_rule("/home", view_func=serve_home, methods=["GET"], strict_slashes=False)
_add_rule("/chat", view_func=serve_chat, methods=["GET"], strict_slashes=False)  # no-redirect, no send_file
_add_rule("/navigation", view_func=serve_navigation, methods=["GET"], strict_slashes=False)
_add_rule("/google_home", view_func=serve_google_home, methods=["GET"], strict_slashes=False)
_add_rule("/", view_func=dashboard.dashboard, methods=["GET"], strict_slashes=False)
_add_rule("/view", view_func=dashboard.dashboard, methods=["GET"], strict_slashes=False)
_add_rule("/control", view_func=dashboard.control_page, methods=["GET"], strict_slashes=False)
_add_rule("/devices", view_func=dashboard.devices_page, methods=["GET"], strict_slashes=False)


# ── Local control fallback ───────────────────────────────────────────────────
def _register_local_control_fallback() -> None:
    """Missing routing uses the canonical handler, never an unguarded BUS publisher."""
    rules_now = {rule.rule for rule in app.url_map.iter_rules()}
    for path in ("/api/control", "/api/cmd"):
        if path not in rules_now:
            app.add_url_rule(path, view_func=control_api.api_control, methods=["POST", "OPTIONS"])


_register_local_control_fallback()


# ── CHAT bootstrap ───────────────────────────────────────────────────────────
def _register_chat_endpoints() -> None:
    register_chat_endpoints(app, _add_rule, _corsify)


# ── BOOTSTRAP ────────────────────────────────────────────────────────────────
try:
    import importlib

    _va = importlib.import_module("services.api_core.vision_api")
    _bp = getattr(_va, "bp", None)
    if _bp is None:
        raise RuntimeError("vision_api.bp missing (circular import?)")
    app.register_blueprint(_bp)  # /vision/*
    # Explicit aliases also work on Flask 1.1 (before blueprint name overrides).
    prefix = _bp.name + "."
    for rule in list(app.url_map.iter_rules()):
        if rule.endpoint.startswith(prefix):
            app.add_url_rule(
                "/api" + rule.rule,
                endpoint="vision_api_alias." + rule.endpoint[len(prefix) :],
                view_func=app.view_functions[rule.endpoint],
                methods=rule.methods,
                provide_automatic_options=rule.provide_automatic_options,
            )
    app.logger.info("[api] vision_api blueprints registered: /vision/* and /api/vision/*")
except Exception as e:
    app.logger.exception("[api] failed to register vision_api blueprint: %s", e)

app.register_blueprint(version_api.bp)

# Register google_proxy blueprint
try:
    app.register_blueprint(google_proxy.google_proxy)
    app.logger.info("[api] google_proxy blueprint registered: /api/google/*")
except Exception as e:
    app.logger.exception("[api] failed to register google_proxy blueprint: %s", e)

# Register services_dashboard blueprint
try:
    from services.api_core.services_dashboard_api import bp as services_dashboard_bp

    if "services_dashboard" not in app.blueprints:
        app.register_blueprint(services_dashboard_bp)
    app.logger.info("[api] services_dashboard blueprint registered: /api/services/*")
except Exception as e:
    app.logger.exception("[api] failed to register services_dashboard blueprint: %s", e)

_register_chat_endpoints()

# Register navigation WebSocket endpoint (optional, controlled by RIDER_NAV_VISUALIZER_ENABLED)
try:
    if os.getenv("RIDER_NAV_VISUALIZER_ENABLED", "false").lower() == "true":
        import importlib

        app.logger.info("[api] Loading optional module: Navigation Visualizer")
        nav_bridge_module = importlib.import_module("services.navigation_websocket_bridge")
        nav_bridge_module.register_websocket_endpoint(app)
        app.logger.info("[api] Navigation Visualizer loaded successfully. Endpoint: /ws/navigation")
    else:
        app.logger.info("[api] Navigation Visualizer is disabled (RIDER_NAV_VISUALIZER_ENABLED!=true)")
except ImportError as e:
    app.logger.error("[api] Failed to load navigation visualizer module: %s", e)
except Exception as e:
    app.logger.error("[api] Unexpected error loading navigation visualizer: %s", e)


def main():
    try:
        if compat:
            compat.start_bus_sub()
            compat.start_xgo_ro()
            compat.start_lcd_idle_guard()
    except Exception as e:
        app.logger.warning("compat init warning: %s", e)
    port = DEFAULT_PORT
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
