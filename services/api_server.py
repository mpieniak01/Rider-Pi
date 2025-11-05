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
    abort,
    jsonify,
    make_response,
    request,
    send_from_directory,
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
import services.api_core.camera as camera
import services.api_core.chat_api as chat_api  # noqa: F401
import services.api_core.control_api as control_api
import services.api_core.control_proxy as control_proxy
import services.api_core.dashboard as dashboard
import services.api_core.face_anim as face_anim
import services.api_core.google_home_api as google_home_api
import services.api_core.google_proxy as google_proxy
import services.api_core.navigator_api as navigator_api
import services.api_core.services_api as services_api
import services.api_core.state_api as state_api
import services.api_core.system_info as system_info
import services.api_core.voice_local_proxy as voice_local_proxy
import services.api_core.voice_proxy as voice_proxy
from services.api_core.face_api import render_face as face_render_shim
from services.api_core.google_home_api import build_auth_url_preview


# ── Metryki API helper ───────────────────────────────────────────────────────
def _update_api_metrics(path: str, status_code: int) -> None:
    """
    Zlicza wywołania API dla interaktywnych endpointów.
    Ignoruje endpointy systemowe, statusy, strumienie i monitoring.
    """
    # Pomijamy endpointy systemowe i monitorujące
    ignore_prefixes = (
        "/healthz",
        "/health",
        "/livez",
        "/readyz",
        "/state",
        "/sysinfo",
        "/metrics",
        "/events",
        "/camera/",
        "/snapshots/",
        "/vision/",
        "/api/status",
        "/api/devices",
        "/api/last_frame",
        "/api/metrics",
        "/api/app-metrics",  # sam siebie też ignorujemy
        "/api/bus/health",
        "/api/flags",
        "/api/version",
        "/api/navigator/status",  # status do odczytu
        "/web/",
        "/",
        "/view",
        "/control",
        "/home",
        "/chat",
        "/system/",
        "/svc",
    )

    if path.startswith(ignore_prefixes):
        return

    # Określamy grupę API na podstawie ścieżki
    group = None
    if path.startswith(("/api/control", "/api/cmd")):
        group = "control"
    elif path.startswith("/api/navigator/"):
        # tylko interaktywne akcje (start/stop/config/return_home)
        if any(
            path.startswith(p)
            for p in [
                "/api/navigator/start",
                "/api/navigator/stop",
                "/api/navigator/config",
                "/api/navigator/return_home",
            ]
        ):
            group = "navigator"
    elif path.startswith("/api/voice/"):
        group = "voice"
    elif path.startswith("/api/home/"):
        # tylko command jest interaktywny
        if path.startswith("/api/home/command"):
            group = "google_home"
    elif path.startswith("/api/chat/send"):
        group = "chat"
    elif path.startswith(("/face/render", "/face/play", "/face/stop", "/api/draw/face")):
        group = "face"

    if group is None:
        return

    # Zliczamy (thread-safe)
    is_ok = status_code < 400
    with compat.API_METRICS_LOCK:
        if is_ok:
            compat.API_METRICS[group]["ok"] += 1
        else:
            compat.API_METRICS[group]["error"] += 1
            compat.API_METRICS_TOTAL["errors"] += 1


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
_add_rule(
    "/api/control/balance",
    view_func=control_api.api_balance,
    methods=["POST", "OPTIONS"],
)
_add_rule("/api/control/height", view_func=control_api.api_height, methods=["POST", "OPTIONS"])

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
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))
    preview = build_auth_url_preview()
    code = 200 if preview.get("ok") else 400
    return _corsify(jsonify(preview)), code


@app.route("/api/home/auth", methods=["POST", "OPTIONS"])
def home_auth():
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))

    # log preview to journald (wrap lines for ruff)
    try:
        import json as _json
        import subprocess

        preview = build_auth_url_preview()
        if preview.get("ok"):
            auth_url = preview.get("auth_url", "")
            port = preview.get("port")

            cmd1 = [
                "/bin/sh",
                "-lc",
                (
                    "printf '%s' "
                    + _json.dumps("[google-oauth] auth_url: " + auth_url)
                    + " | systemd-cat -t rider-api-env -p info"
                ),
            ]
            subprocess.run(cmd1, check=False)

            if port:
                cmd2 = [
                    "/bin/sh",
                    "-lc",
                    (
                        "printf '%s' "
                        + _json.dumps("[google-oauth] loopback port: " + str(port))
                        + " | systemd-cat -t rider-api-env -p info"
                    ),
                ]
                subprocess.run(cmd2, check=False)
    except Exception as _e:
        app.logger.warning("auth preview log failed: %s", _e)

    try:
        result = google_home_api.start_oauth_flow()
        status_code = 200 if result.get("ok") else 500
        return _corsify(jsonify(result)), status_code
    except Exception as e:
        app.logger.error("OAuth flow error: %s", e, exc_info=True)
        return _corsify(jsonify({"ok": False, "error": "Authentication configuration error"})), 500


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

    # Zwracamy kopię, aby uniknąć race condition przy odczycie (thread-safe)
    with compat.API_METRICS_LOCK:
        metrics_snapshot = {group: dict(counts) for group, counts in compat.API_METRICS.items()}
        total_errors = compat.API_METRICS_TOTAL["errors"]

    return jsonify(
        {
            "ok": True,
            "metrics": metrics_snapshot,
            "total_errors": total_errors,
        }
    ), 200


# ── Static / dashboard ───────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_WEB_DIR = os.path.abspath(os.getenv("WEB_DIR") or os.path.join(os.path.dirname(BASE_DIR), "web"))


def _no_cache(resp: Response) -> Response:
    """Wspólne nagłówki anti-cache dla statyków."""
    try:
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    except Exception:
        pass
    return resp


def serve_web(fname: str):
    """Serwuje pliki z katalogu web/ (wyłącznie pliki, brak tras katalogowych)."""
    if not fname or ".." in fname or fname.startswith(("/", "\\")):
        abort(404)
    resp = send_from_directory(STATIC_WEB_DIR, fname)
    return _no_cache(resp)


def serve_home():
    """Krótka trasa /home → web/home.html (bez katalogów, bez redirectów)."""
    return _no_cache(send_from_directory(STATIC_WEB_DIR, "home.html"))


def serve_chat():
    """Krótka trasa /chat → web/chat.html bez 30x."""
    chat_path = os.path.join(STATIC_WEB_DIR, "chat.html")
    if not os.path.isfile(chat_path):
        abort(404)
    # czytaj surowo, ustaw content-type i anti-cache
    with open(chat_path, "rb") as f:
        data = f.read()
    resp = make_response(data, 200)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return _no_cache(resp)


def serve_navigation():
    """Krótka trasa /navigation → web/navigation.html"""
    nav_path = os.path.join(STATIC_WEB_DIR, "navigation.html")
    if not os.path.isfile(nav_path):
        abort(404)
    # czytaj surowo, ustaw content-type i anti-cache
    with open(nav_path, "rb") as f:
        data = f.read()
    resp = make_response(data, 200)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return _no_cache(resp)


_add_rule("/web/<path:fname>", view_func=serve_web, methods=["GET"], strict_slashes=False)
_add_rule("/home", view_func=serve_home, methods=["GET"], strict_slashes=False)
_add_rule("/chat", view_func=serve_chat, methods=["GET"], strict_slashes=False)  # no-redirect, no send_file
_add_rule("/navigation", view_func=serve_navigation, methods=["GET"], strict_slashes=False)
_add_rule("/", view_func=dashboard.dashboard, methods=["GET"], strict_slashes=False)
_add_rule("/view", view_func=dashboard.dashboard, methods=["GET"], strict_slashes=False)
_add_rule("/control", view_func=dashboard.control_page, methods=["GET"], strict_slashes=False)


# ── Local control fallback ───────────────────────────────────────────────────
def _register_local_control_fallback() -> None:
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
            app.logger.warning("[control-local] pyzmq not available or BUS connect failed: %s", _e)

        def _control_local():
            if _req.method == "OPTIONS":
                return _corsify(_mk("", 204))
            payload = _req.get_json(silent=True) or {}
            if "cmd" not in payload:
                payload = {"cmd": "move", "dir": payload.get("dir", "stop")}
            info: dict[str, Any] = {"ok": True, "mode": "local", "published": False}
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
        app.logger.warning("[control-local] fallback not active: %s", e)


_register_local_control_fallback()


# ── CHAT bootstrap ───────────────────────────────────────────────────────────
def _register_chat_endpoints() -> None:
    try:
        if hasattr(chat_api, "register"):
            chat_api.register(app)
            app.logger.info("[chat] blueprint/handlers registered via chat_api.register(app)")
    except Exception as e:
        app.logger.warning("[chat] register(app) failed: %s", e)

    rules_now = {r.rule for r in app.url_map.iter_rules()}
    need_history = "/api/chat/history" not in rules_now
    need_send = "/api/chat/send" not in rules_now
    need_ping = "/api/chat/ping" not in rules_now
    if not (need_history or need_send or need_ping):
        return

    try:
        from services.api_core import chat_store as _chat_store  # type: ignore
    except Exception as e:
        _chat_store = None  # type: ignore
        app.logger.warning("[chat] chat_store import failed: %s", e)

    def _ok(data: dict[str, Any], code: int = 200):
        return _corsify(jsonify({"ok": True, **data})), code

    def _err(msg: str, code: int = 400):
        return _corsify(jsonify({"ok": False, "error": msg})), code

    if need_ping:

        def _chat_ping():
            if request.method == "OPTIONS":
                return _corsify(make_response("", 204))
            return _ok({"service": "chat", "mode": "fallback"})

        _add_rule("/api/chat/ping", view_func=_chat_ping, methods=["GET", "OPTIONS"])

    if need_history:

        def _chat_history():
            if request.method == "OPTIONS":
                return _corsify(make_response("", 204))
            limit = request.args.get("limit")
            try:
                n = int(limit) if limit is not None else None
            except Exception:
                n = None
            try:
                if _chat_store and hasattr(_chat_store, "history"):
                    items = list(_chat_store.history(n))  # type: ignore[attr-defined]
                elif _chat_store and hasattr(_chat_store, "get_store"):
                    items = _chat_store.get_store().list(limit=n)  # type: ignore[call-arg]
                else:
                    items = []
                return _ok({"items": items})
            except Exception as e:
                return _err(f"history_failed: {e}", 500)

        _add_rule("/api/chat/history", view_func=_chat_history, methods=["GET", "OPTIONS"])

    if need_send:

        def _chat_send():
            if request.method == "OPTIONS":
                return _corsify(make_response("", 204))
            payload = request.get_json(silent=True) or {}
            msg = (payload.get("msg") or "").strip()
            user = (payload.get("user") or "web").strip()
            if not msg:
                return _err("empty_msg", 400)
            try:
                if _chat_store and hasattr(_chat_store, "append"):
                    item = _chat_store.append({"msg": msg, "user": user})  # type: ignore[attr-defined]
                elif _chat_store and hasattr(_chat_store, "get_store"):
                    item = _chat_store.get_store().add(msg=msg, user=user)  # type: ignore[attr-defined]
                else:
                    item = {"msg": msg, "user": user}
                return _ok({"item": item})
            except Exception as e:
                return _err(f"send_failed: {e}", 500)

        _add_rule("/api/chat/send", view_func=_chat_send, methods=["POST", "OPTIONS"])

    app.logger.info(
        "[chat] fallback endpoints active: "
        f"{'history ' if need_history else ''}"
        f"{'send ' if need_send else ''}"
        f"{'ping' if need_ping else ''}".strip()
    )


# ── BOOTSTRAP ────────────────────────────────────────────────────────────────
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

# Register google_proxy blueprint
try:
    app.register_blueprint(google_proxy.google_proxy)
    app.logger.info("[api] google_proxy blueprint registered: /api/google/*")
except Exception as e:
    app.logger.exception("[api] failed to register google_proxy blueprint: %s", e)

# Register services_dashboard blueprint
try:
    from services.api_core.services_dashboard_api import bp as services_dashboard_bp

    app.register_blueprint(services_dashboard_bp)
    app.logger.info("[api] services_dashboard blueprint registered: /api/services/*")
except Exception as e:
    app.logger.exception("[api] failed to register services_dashboard blueprint: %s", e)

_register_chat_endpoints()

# Register navigation WebSocket endpoint (optional, controlled by RIDER_NAV_VISUALIZER_ENABLED)
try:
    if os.getenv("RIDER_NAV_VISUALIZER_ENABLED", "false").lower() == "true":
        app.logger.info("[api] Loading optional module: Navigation Visualizer")
        import importlib

        nav_bridge_module = importlib.import_module("services.navigation_websocket_bridge")
        register_websocket_endpoint = getattr(nav_bridge_module, "register_websocket_endpoint")
        register_websocket_endpoint(app)
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
    except Exception as e:
        app.logger.warning("compat init warning: %s", e)
    port = DEFAULT_PORT
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
