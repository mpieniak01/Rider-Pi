#!/usr/bin/env python3
"""
Rider-Pi – core kompatybilności:
- globalny stan (LAST_*)
- konfiguracja/ścieżki
- endpointy: /healthz, /health, /livez, /readyz, /state, /sysinfo, /metrics, /events
- aliasy /api/*: /api/status, /api/metrics (JSON), /api/devices, /api/last_frame, /api/flags
- /api/version, /api/bus/health
- start_bus_sub(), start_xgo_ro()
"""

from __future__ import annotations

import collections
import itertools
import json
import os
import subprocess  # noqa: F401 - compatibility namespace used by health handlers
import sys
import threading
import time
from collections import deque
from typing import Any

from flask import (
    Flask,
    Response,
    jsonify,
    make_response,
    request,
    send_file,
    stream_with_context,  # noqa: F401 - public namespace used by event handler
)

import services.api_core.face_api as face_api
from services.api_core import compat_health
from services.api_core.services_dashboard_api import bp as services_dashboard_bp

from .http_security import apply_cors, install as install_http_security

# ── Konfiguracja ───────────────────────────────────────────────────────────────
BUS_PUB_PORT = int(os.getenv("BUS_PUB_PORT", "5555"))
BUS_SUB_PORT = int(os.getenv("BUS_SUB_PORT", "5556"))
STATUS_API_PORT = int(os.getenv("STATUS_API_PORT") or os.getenv("API_PORT") or "8080")
REQUIRE_VISION_HB = os.getenv("REQUIRE_VISION_HEARTBEAT", "0") == "1"

ENV_DISABLE_LCD = os.getenv("DISABLE_LCD", "0") == "1"
ENV_NO_DRAW = os.getenv("NO_DRAW", "0") == "1"
ENV_ROT = int(os.getenv("PREVIEW_ROT", "0") or 0)

REFRESH_S = 2.0
HISTORY_LEN = 60

# ── Ścieżki ───────────────────────────────────────────────────────────────────
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Import camera config for snapshot paths
try:
    from apps.camera.config import load_config as load_camera_config

    _camera_cfg = load_camera_config()
    SNAP_DIR = _camera_cfg.snap_dir
    RAW_PATH = _camera_cfg.raw_path
    PROC_PATH = _camera_cfg.proc_path
    SSD_PATH = _camera_cfg.ssd_path
except (ImportError, ModuleNotFoundError):
    # Fallback to legacy ENV-based paths if config module unavailable
    SNAP_DIR = os.path.abspath(os.getenv("SNAP_DIR") or os.getenv("SNAP_BASE") or os.path.join(BASE_DIR, "snapshots"))
    RAW_PATH = os.getenv("RAW_PATH") or os.path.join(SNAP_DIR, "raw.jpg")
    PROC_PATH = os.getenv("PROC_PATH") or os.path.join(SNAP_DIR, "proc.jpg")
    SSD_PATH = os.getenv("SSD_PATH") or os.path.join(SNAP_DIR, "ssd.jpg")

VIEW_HTML = os.path.abspath(os.path.join(BASE_DIR, "web", "view.html"))
CONTROL_HTML = os.path.abspath(os.path.join(BASE_DIR, "web", "control.html"))
SYSTEM_HTML = os.path.abspath(os.path.join(BASE_DIR, "web", "system.html"))

# ── Aplikacja Flask ───────────────────────────────────────────────────────────
app = Flask(__name__)


install_http_security(app)

# Flask < 2.0 shim
if not hasattr(app, "get"):

    def _get(rule, **opts):
        opts.setdefault("methods", ["GET"])
        return app.route(rule, **opts)

    def _post(rule, **opts):
        opts.setdefault("methods", ["POST"])
        return app.route(rule, **opts)

    app.get = _get  # type: ignore
    app.post = _post  # type: ignore

# Rejestracja blueprintu system dashboardu (API: /api/services/graph)
app.register_blueprint(services_dashboard_bp)


@app.get("/system/")
def system_dashboard_html():
    """Główny widok System Dashboard pod krótką trasą /system/."""
    return send_file(SYSTEM_HTML)


# ── Start timestamp (używany w wielu endpointach) ─────────────────────────────
START_TS = time.time()

# ── Detekcja pyzmq (na potrzeby /readyz i /api/bus/health) ───────────────────
try:
    import zmq  # noqa: F401

    _ZMQ_OK = True
except Exception:
    _ZMQ_OK = False

# ── Globalny stan ─────────────────────────────────────────────────────────────
LAST_MSG_TS = None
LAST_HEARTBEAT_TS = None
LAST_STATE = {"present": False, "confidence": 0.0, "mode": None, "ts": None}

LAST_CAMERA = {
    "ts": None,
    "mode": None,
    "fps": None,
    "lcd": {
        "enabled_env": (not ENV_DISABLE_LCD),
        "no_draw": ENV_NO_DRAW,
        "rot": ENV_ROT,
        "active": False,
        "on": None,
        "power_known": False,
        "presenting": False,
        "holders": [],
        "checked_at": None,
        "auto_off_ts": None,
    },
}

LAST_XGO = {
    "ts": None,
    "imu_ok": False,
    "pose": None,
    "battery": None,
    "roll": None,
    "pitch": None,
    "yaw": None,
}
XGO_FW = None

LAST_BALANCE = {"enabled": None, "ts": None}
LAST_HEIGHT = {"value": None, "ts": None}
LAST_TRACKING_MODE = {"mode": "none", "enabled": False, "ts": None}
LAST_TRACKING_OFFSET = {"offset": None, "mode": None, "ts": None}
LAST_NAVIGATOR = {
    "active": False,
    "state": None,
    "strategy": None,
    "obstacle_present": None,
    "ts": None,
}
MOTION_QUEUE = deque(maxlen=int(os.getenv("MOTION_QUEUE_MAX", "50")))

# Historia
HIST_CPU = collections.deque(maxlen=HISTORY_LEN)
HIST_MEM = collections.deque(maxlen=HISTORY_LEN)
EVENTS = collections.deque(maxlen=200)

ENABLE_XGO_RO = os.getenv("ENABLE_XGO_RO", "1") == "1"

# ── Metryki API (app-level) ──────────────────────────────────────────────────
# Liczniki OK/Error dla interaktywnych endpointów API (bez systemu/monitoringu)
API_METRICS = {
    "control": {"ok": 0, "error": 0},
    "navigator": {"ok": 0, "error": 0},
    "voice": {"ok": 0, "error": 0},
    "google_home": {"ok": 0, "error": 0},
    "chat": {"ok": 0, "error": 0},
    "face": {"ok": 0, "error": 0},
}
# Używamy słownika dla mutability w kontekście modułu
API_METRICS_TOTAL = {"errors": 0}
# Global lock for thread-safe mutation of API_METRICS and API_METRICS_TOTAL
API_METRICS_LOCK = threading.Lock()

# All mutations to API_METRICS and API_METRICS_TOTAL must be protected by API_METRICS_LOCK.


# ── Pomocnicze: sanity i konwersje ────────────────────────────────────────────
def _sanitize_fw(v):
    if v is None:
        return None
    s = str(v).strip()
    return None if s.lower() in ("null", "", "none", "0") else s


def _voltage_to_pct(v: float) -> int | None:
    try:
        vf = float(v)
    except Exception:
        return None
    if 9.3 <= vf <= 12.9:
        v_min, v_max = 9.6, 12.6  # 3S
    elif 6.0 <= vf <= 8.7:
        v_min, v_max = 6.4, 8.4  # 2S
    else:
        return None
    pct = (vf - v_min) / (v_max - v_min) * 100.0
    return int(max(0, min(100, round(pct))))


def _coerce_batt_like(v) -> int | None:
    if v is None:
        return None
    try:
        f = float(v)
    except Exception:
        return None
    if 0.0 <= f <= 1.0:
        return int(round(f * 100.0))
    if 1.0 < f <= 100.0:
        return int(round(f))
    return _voltage_to_pct(f)


def _sanitize_batt(v):
    pct = _coerce_batt_like(v)
    return pct if pct is not None else None


def _norm_angle180(v):
    try:
        a = float(v)
    except Exception:
        return v
    a = ((a + 180.0) % 360.0) - 180.0
    return round(a, 2)


def _classify_pose(roll, pitch):
    try:
        r, p = abs(float(roll)), abs(float(pitch))
        if r < 20 and p < 20:
            return "upright"
        if r > 60 or p > 60:
            return "fallen"
        return "leaning"
    except Exception:
        return None


# ── Bus publish (opcjonalny) ─────────────────────────────────────────────────
_BUS_PUB = None
_BUS_PUB_LOCK = threading.Lock()


def _get_bus_pub():
    global _BUS_PUB
    if _BUS_PUB is not None:
        return _BUS_PUB
    with _BUS_PUB_LOCK:
        if _BUS_PUB is None:
            warmup_ms = int(float(os.getenv("API_BUS_PUB_WARMUP_S", "0.2")) * 1000)
            try:
                from common.bus import BusPub

                _BUS_PUB = BusPub(warmup_ms=warmup_ms)
            except Exception:
                _BUS_PUB = None
        return _BUS_PUB


def bus_pub(topic: str, payload: dict, *, add_ts: bool = False):
    if add_ts is not False:
        raise ValueError("producer timestamps must remain unchanged")
    pub = _get_bus_pub()
    if pub is None:
        return
    try:
        pub.publish(topic, payload, add_ts=add_ts)
    except Exception:
        pass


def motion_queue_append(entry: dict[str, Any]) -> None:
    """Store latest motion control command."""
    if not isinstance(entry, dict):
        return
    normalized = dict(entry)
    try:
        normalized["ts"] = float(normalized.get("ts") or time.time())
    except Exception:
        normalized["ts"] = time.time()
    MOTION_QUEUE.appendleft(normalized)


def motion_queue_snapshot(limit: int = 10) -> list[dict[str, Any]]:
    """Return most recent motion commands."""
    if limit and limit > 0:
        return list(itertools.islice(MOTION_QUEUE, limit))
    return list(MOTION_QUEUE)


def motion_queue_clear() -> None:
    """Clear stored motion commands."""
    MOTION_QUEUE.clear()


# ── System info (delegacja do modułu) ────────────────────────────────────────
# Funkcje sysinfo/metrics delegowane są do services.api_core.system_info.


# ── Middleware ────────────────────────────────────────────────────────────────
@app.after_request
def log_and_secure(resp):
    try:
        print(f"[api] {request.method} {request.path}", flush=True)
    except Exception:
        pass
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp


# ── Endpointy ────────────────────────────────────────────────────────────────
def healthz():
    return compat_health.healthz(sys.modules[__name__])


def health_alias():
    return compat_health.health_alias(sys.modules[__name__])


def livez():
    return compat_health.livez(sys.modules[__name__])


# === Version / Bus health / Refined readyz ====================================
def _git_info():
    return compat_health._git_info(sys.modules[__name__])


def api_version():
    return compat_health.api_version(sys.modules[__name__])


def api_bus_health():
    return compat_health.api_bus_health(sys.modules[__name__])


def readyz():
    return compat_health.readyz(sys.modules[__name__])


# === Flags (zgodne z dawnym plikiem data/flags/*) =============================
FLAGS_DIR = os.path.join(BASE_DIR, "data", "flags")
os.makedirs(FLAGS_DIR, exist_ok=True)


def _flag_path(name: str) -> str:
    # nazwy wspierane: motion.enable, estop.on
    safe = name.replace("/", "_")
    return os.path.join(FLAGS_DIR, safe)


def _read_flags() -> dict:
    estop = os.path.isfile(_flag_path("estop.on"))
    motion = os.path.isfile(_flag_path("motion.enable"))
    return {"estop": estop, "motion_enable": motion}


def _set_flag(name: str, state: bool) -> bool:
    p = _flag_path(name)
    try:
        if state:
            open(p, "a").close()
        else:
            if os.path.isfile(p):
                os.remove(p)
        return True
    except Exception:
        return False


# === /api/status ==============================================================
def api_status():
    return compat_health.api_status(sys.modules[__name__])


# === /api/metrics (JSON kompatybilny ze starym API) ===========================
def api_metrics_alias():
    return compat_health.api_metrics_alias(sys.modules[__name__])


# === /api/devices (zbiorcza meta) ============================================
def api_devices():
    return compat_health.api_devices(sys.modules[__name__])


# === /api/last_frame (meta) ===================================================
def api_last_frame():
    return compat_health.api_last_frame(sys.modules[__name__])


# === /api/flags (GET + POST /api/flags/<name>/<on|off>) ======================
def api_flags_get():
    return Response(json.dumps(_read_flags()), mimetype="application/json")


def api_flags_set(name: str, state: str):
    """Legacy flags cannot arm the robot or clear its emergency latch."""
    from services.control_commands import submit_control

    actions = {("estop.on", "on"): "estop", ("motion.enable", "off"): "disarm"}
    action = actions.get((name.strip().lower(), state.strip().lower()))
    if action is None:
        return jsonify({"ok": False, "error": "use_explicit_safety_operator_plan", "endpoint": "/api/safety"}), 409
    body, code = submit_control({"action": action})
    return jsonify(body), code


def state():
    from .state_api import state as _state

    return _state()


def sysinfo():
    from .system_info import sysinfo as _sysinfo

    return _sysinfo()


def metrics():
    from .system_info import metrics as _metrics

    return _metrics()


def events():
    return compat_health.events(sys.modules[__name__])


# ── Startery wątków ──────────────────────────────────────────────────────────
def start_bus_sub():
    """Uruchom pętlę subskrypcji BUS (idempotentnie)."""
    if getattr(start_bus_sub, "_started", False):
        return
    from . import devices  # local import to avoid circular

    t = threading.Thread(target=devices.bus_sub_loop, daemon=True)
    t.start()
    start_bus_sub._started = True
    print("[api] bus_sub_loop started", flush=True)


def start_xgo_ro():
    """Compatibility: consume executor telemetry; API never owns a second UART."""
    start_bus_sub()


def start_lcd_idle_guard():
    """Uruchom strażnik wygaszający LCD przy bezczynności."""
    if getattr(start_lcd_idle_guard, "_started", False):
        return
    try:
        from services import lcd_idle_guard

        started = lcd_idle_guard.start()
        start_lcd_idle_guard._started = True
        if started:
            print("[api] lcd_idle_guard started", flush=True)
        else:
            print("[api] lcd_idle_guard skipped (disabled or already running)", flush=True)
    except Exception as e:
        start_lcd_idle_guard._started = True
        print("[api] lcd_idle_guard unavailable — skipping", e, flush=True)


# ===== MONKEY-PATCH: /api/control → proxy do :8081/control (POST/OPTIONS) =====
try:
    import requests  # type: ignore
except Exception:
    requests = None


def _api_control_proxy_impl():
    """Legacy entry delegates to the canonical gate and retains its refusal/ACK."""
    from .control_api import api_control

    return api_control()


# Przeregistruj trasę: usuń wszystkie stare /api/control i dodaj jedną POST/OPTIONS
try:
    to_remove = [r for r in list(app.url_map.iter_rules()) if r.rule == "/api/control"]
    for r in to_remove:
        try:
            app.url_map._rules.remove(r)
            app.url_map._rules_by_endpoint[r.endpoint].remove(r)
        except Exception:
            pass
    app.add_url_rule(
        "/api/control_legacy",
        endpoint="api_control_legacy",
        view_func=_api_control_proxy_impl,
        methods=["POST", "OPTIONS"],
    )
    print("[api] /api/control proxy(v2): route installed (POST,OPTIONS)", flush=True)
except Exception as _e:
    print("[api] /api/control proxy(v2): bind failed:", _e, flush=True)
# ===== KONIEC PATCHA =====


def draw_face_route():
    # proxy CORS tak jak w voice_proxy
    try:
        if request.method == "OPTIONS":
            return voice_proxy._corsify(make_response("", 204))  # noqa: F821
    except Exception:
        pass
    payload = request.get_json(silent=True) or {}
    preview = face_api.png_response(payload)
    if preview is not None:
        return preview
    body, code = face_api.draw_face(payload)
    try:
        return voice_proxy._corsify(jsonify(body)), code  # noqa: F821
    except Exception:
        # fallback gdyby voice_proxy nie miał _corsify
        resp = jsonify(body)
        apply_cors(resp)
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        return resp, code


app.add_url_rule(
    "/api/draw/face",
    view_func=draw_face_route,
    methods=["POST", "OPTIONS"],
)
app.add_url_rule(
    "/draw/face",
    view_func=draw_face_route,
    methods=["POST", "OPTIONS"],
)
