# services/api_server.py
from __future__ import annotations

import os
from typing import Any

from flask import Flask, Response, jsonify, make_response, request, send_from_directory

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
import services.api_core.chat_api as chat_api  # noqa: F401  # Chat/glue
import services.api_core.control_proxy as control_proxy
import services.api_core.dashboard as dashboard
import services.api_core.face_anim as face_anim
import services.api_core.google_home_api as google_home_api
import services.api_core.services_api as services_api  # właściwy moduł usług
import services.api_core.state_api as state_api
import services.api_core.system_info as system_info
import services.api_core.voice_local_proxy as voice_local_proxy  # lokalny TTS/ASR proxy
import services.api_core.voice_proxy as voice_proxy
from services.api_core.face_api import render_face as face_render_shim


# ── CORS global ──────────────────────────────────────────────────────────────
@app.after_request
def _cors_all(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS,HEAD"
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

# voice proxy (zdalne/istniejące)
_add_rule("/api/voice/capture", view_func=voice_proxy.capture_handler, methods=["POST", "OPTIONS"])
_add_rule("/api/voice/say", view_func=voice_proxy.say_handler, methods=["POST", "OPTIONS"])

# voice local proxy (NOWE – lokalny kanał TTS/ASR via :8092)
_add_rule("/api/voice/tts", view_func=voice_local_proxy.tts_local_handler, methods=["POST", "OPTIONS"])
_add_rule("/api/voice/asr", view_func=voice_local_proxy.asr_local_handler, methods=["POST", "OPTIONS"])


# ── GOOGLE HOME ──────────────────────────────────────────────────────────────
def _auto_refresh_token_and_retry(api_call, *args, **kwargs):
    """
    Helper to automatically refresh token on 401 and retry the API call.

    Args:
        api_call: Function to call (get_devices or send_command)
        *args, **kwargs: Arguments to pass to the API call

    Returns:
        Result dictionary from the API call
    """
    result = api_call(*args, **kwargs)

    # Auto-refresh token on 401
    if result.get("status_code") == 401:
        token = google_home_api.refresh_access_token()
        if token:
            result = api_call(*args, **kwargs)

    return result


@app.route("/api/home/auth", methods=["GET"])
def home_auth():
    """Start OAuth 2.0 flow for Google Home."""
    try:
        auth_url = google_home_api.get_auth_url()
        from flask import redirect

        return redirect(auth_url)
    except Exception as e:
        app.logger.error(f"Error starting OAuth flow: {e}", exc_info=True)
        return _corsify(jsonify({"ok": False, "error": "Authentication configuration error"})), 500


@app.route("/api/home/oauth2callback", methods=["GET"])
def home_oauth_callback():
    """Handle OAuth 2.0 callback from Google."""
    code = request.args.get("code")
    if not code:
        return _corsify(jsonify({"ok": False, "error": "No authorization code provided"})), 400

    result = google_home_api.handle_oauth_callback(code)

    if result.get("ok"):
        # Redirect to home.html after successful auth
        from flask import redirect

        return redirect("/web/home.html?auth=success")
    else:
        # Log that authentication failed (without sensitive details)
        app.logger.error("OAuth callback failed")
        return _corsify(jsonify({"ok": False, "error": "Authentication failed"})), 500


@app.route("/api/home/status", methods=["GET", "OPTIONS"])
def home_status():
    """Check authentication status."""
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))

    is_auth = google_home_api.is_authenticated()
    return _corsify(jsonify({"ok": True, "authenticated": is_auth})), 200


@app.route("/api/home/devices", methods=["GET", "OPTIONS"])
def home_devices():
    """Get list of devices from Google Home."""
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))

    result = _auto_refresh_token_and_retry(google_home_api.get_devices)

    if result.get("ok"):
        # Success - return only the devices, not internal details
        return _corsify(jsonify({"ok": True, "devices": result.get("devices", [])})), 200
    else:
        # Log actual error but return generic message
        app.logger.error(f"Failed to get devices: {result.get('error', 'Unknown error')}")
        error_msg = "Not authenticated" if result.get("status_code") == 401 else "Failed to retrieve devices"
        status_code = 401 if result.get("status_code") == 401 else 500
        return _corsify(jsonify({"ok": False, "error": error_msg})), status_code


@app.route("/api/home/command", methods=["POST", "OPTIONS"])
def home_command():
    """Send command to a Google Home device."""
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))

    payload = request.get_json(silent=True) or {}
    device_id = payload.get("deviceId")
    command = payload.get("command")
    params = payload.get("params", {})

    if not device_id or not command:
        return _corsify(jsonify({"ok": False, "error": "Missing deviceId or command"})), 400

    result = _auto_refresh_token_and_retry(google_home_api.send_command, device_id, command, params)

    if result.get("ok"):
        # Success
        return _corsify(jsonify({"ok": True})), 200
    else:
        # Log actual error but return generic message
        app.logger.error(f"Failed to send command: {result.get('error', 'Unknown error')}")
        error_msg = "Not authenticated" if result.get("status_code") == 401 else "Command failed"
        status_code = 401 if result.get("status_code") == 401 else 500
        return _corsify(jsonify({"ok": False, "error": error_msg})), status_code


# bus health (stub)
@app.route("/api/bus/health", methods=["GET", "OPTIONS"])
def _bus_health():
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))
    return _corsify(jsonify({"ok": True})), 200


# ── Static / dashboard ───────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_WEB_DIR = os.path.abspath(os.getenv("WEB_DIR") or os.path.join(os.path.dirname(BASE_DIR), "web"))


def serve_web(fname: str):
    """Serwuje statyki z twardym anti-cache, żeby UI zawsze widział świeże pliki."""
    resp = send_from_directory(STATIC_WEB_DIR, fname)
    try:
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    except Exception:
        pass
    return resp


_add_rule("/web/<path:fname>", view_func=serve_web, methods=["GET"])
_add_rule("/", view_func=dashboard.dashboard, methods=["GET"])
_add_rule("/control", view_func=dashboard.control_page, methods=["GET"])


# ── Local control fallback (przed startem serwera) ───────────────────────────
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
            app.logger.warning(f"[control-local] pyzmq not available or BUS connect failed: {_e}")

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
        app.logger.warning(f"[control-local] fallback not active: {e}")


_register_local_control_fallback()


# ── CHAT: rejestracja + bezpieczny fallback ──────────────────────────────────
def _register_chat_endpoints() -> None:
    """Rejestruje chat_api jeśli ma register(app); dodaje minimalny fallback,
    gdy trasy nie istnieją. Idempotentne."""
    # 1) Spróbuj zarejestrować przez modułowy register(app)
    try:
        if hasattr(chat_api, "register"):
            chat_api.register(app)  # może dodać /api/chat/history, /api/chat/send, itp.
            app.logger.info("[chat] blueprint/handlers registered via chat_api.register(app)")
    except Exception as e:
        app.logger.warning(f"[chat] register(app) failed: {e}")

    # 2) Fallback tylko jeśli dalej brak tras
    rules_now = {r.rule for r in app.url_map.iter_rules()}
    need_history = "/api/chat/history" not in rules_now
    need_send = "/api/chat/send" not in rules_now
    need_ping = "/api/chat/ping" not in rules_now

    if not (need_history or need_send or need_ping):
        return

    # Lokalny, prosty magazyn (zgodny z chat_store.*)
    try:
        from services.api_core import chat_store as _chat_store  # type: ignore
    except Exception as e:  # awaryjnie pusty store in-memory
        _chat_store = None  # type: ignore
        app.logger.warning(f"[chat] chat_store import failed: {e}")

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
                    items = []  # brak magazynu
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
                    # awaryjnie echo
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

# --- rejestracja czatu (blueprint lub fallback) ---
_register_chat_endpoints()


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
