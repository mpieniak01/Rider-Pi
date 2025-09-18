#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
import os, time, json, threading, collections, subprocess, platform, shutil
from typing import Optional
from flask import Flask, Response, stream_with_context, request, jsonify, send_file

# ── Konfiguracja ───────────────────────────────────────────────────────────────
BUS_PUB_PORT = int(os.getenv("BUS_PUB_PORT", "5555"))
BUS_SUB_PORT = int(os.getenv("BUS_SUB_PORT", "5556"))
STATUS_API_PORT = int(os.getenv("STATUS_API_PORT") or os.getenv("API_PORT") or "8080")
REQUIRE_VISION_HB = (os.getenv("REQUIRE_VISION_HEARTBEAT", "0") == "1")

ENV_DISABLE_LCD = (os.getenv("DISABLE_LCD", "0") == "1")
ENV_NO_DRAW     = (os.getenv("NO_DRAW", "0") == "1")
ENV_ROT         = int(os.getenv("PREVIEW_ROT", "0") or 0)

REFRESH_S   = 2.0
HISTORY_LEN = 60

# ── Ścieżki ───────────────────────────────────────────────────────────────────
BASE_DIR      = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SNAP_DIR      = os.path.abspath(os.getenv("SNAP_DIR") or os.getenv("SNAP_BASE") or os.path.join(BASE_DIR, "snapshots"))
VIEW_HTML     = os.path.abspath(os.path.join(BASE_DIR, "web", "view.html"))
CONTROL_HTML  = os.path.abspath(os.path.join(BASE_DIR, "web", "control.html"))
RAW_PATH      = os.path.join(SNAP_DIR, "raw.jpg")
PROC_PATH     = os.path.join(SNAP_DIR, "proc.jpg")

# ── Aplikacja Flask ───────────────────────────────────────────────────────────
app = Flask(__name__)

# Flask < 2.0 shim
if not hasattr(app, "get"):
    def _get(rule, **opts):
        opts.setdefault("methods", ["GET"]);  return app.route(rule, **opts)
    def _post(rule, **opts):
        opts.setdefault("methods", ["POST"]); return app.route(rule, **opts)
    app.get = _get   # type: ignore
    app.post = _post # type: ignore

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
    "ts": None, "mode": None, "fps": None,
    "lcd": {"enabled_env": (not ENV_DISABLE_LCD), "no_draw": ENV_NO_DRAW, "rot": ENV_ROT, "active": False},
}

LAST_XGO = {"ts": None, "imu_ok": False, "pose": None, "battery": None, "roll": None, "pitch": None, "yaw": None}
XGO_FW = None

# Historia
HIST_CPU = collections.deque(maxlen=HISTORY_LEN)
HIST_MEM = collections.deque(maxlen=HISTORY_LEN)
EVENTS   = collections.deque(maxlen=200)

ENABLE_XGO_RO = (os.getenv("ENABLE_XGO_RO", "1") == "1")

# ── Pomocnicze: sanity i konwersje ────────────────────────────────────────────
def _sanitize_fw(v):
    if v is None: return None
    s = str(v).strip()
    return None if s.lower() in ("null", "", "none", "0") else s

def _voltage_to_pct(v: float) -> Optional[int]:
    try: vf = float(v)
    except Exception: return None
    if 9.3 <= vf <= 12.9:     v_min, v_max = 9.6, 12.6   # 3S
    elif 6.0 <= vf <= 8.7:    v_min, v_max = 6.4, 8.4   # 2S
    else: return None
    pct = (vf - v_min) / (v_max - v_min) * 100.0
    return int(max(0, min(100, round(pct))))

def _coerce_batt_like(v) -> Optional[int]:
    if v is None: return None
    try: f = float(v)
    except Exception: return None
    if 0.0 < f <= 1.0:   return int(round(f * 100.0))
    if 1.0 < f <= 100.0: return int(round(f))
    return _voltage_to_pct(f)

def _sanitize_batt(v):
    pct = _coerce_batt_like(v)
    return pct if pct is not None else None

def _norm_angle180(v):
    try: a = float(v)
    except Exception: return v
    a = ((a + 180.0) % 360.0) - 180.0
    return round(a, 2)

def _classify_pose(roll, pitch):
    try:
        r, p = abs(float(roll)), abs(float(pitch))
        if r < 20 and p < 20: return "upright"
        if r > 60 or p > 60:  return "fallen"
        return "leaning"
    except Exception:
        return None

# ── Bus publish (opcjonalny) ─────────────────────────────────────────────────
def bus_pub(topic: str, payload: dict):
    try:
        import zmq  # late import by need
        ctx = zmq.Context.instance()
        pub = ctx.socket(zmq.PUB)
        pub.connect(f"tcp://127.0.0.1:{BUS_PUB_PORT}")
        pub.send_string(f"{topic} {json.dumps(payload, ensure_ascii=False)}")
    except Exception:
        pass

# ── System info (delegacja do modułu) ────────────────────────────────────────
# Funkcje sysinfo/metrics delegowane są do services.api_core.system_info.

# ── Middleware ────────────────────────────────────────────────────────────────
@app.after_request
def log_and_secure(resp):
    try: print(f"[api] {request.method} {request.path}", flush=True)
    except Exception: pass
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp

# ── Endpointy ────────────────────────────────────────────────────────────────
def healthz():
    now = time.time()
    last_msg_age = (now - LAST_MSG_TS) if LAST_MSG_TS else None
    last_hb_age  = (now - LAST_HEARTBEAT_TS) if LAST_HEARTBEAT_TS else None

    cam_ts  = LAST_CAMERA.get("ts")
    cam_age = (now - cam_ts) if cam_ts else None
    camera_on = (cam_age is not None and cam_age <= 5.0)

    xgo_ts  = LAST_XGO.get("ts")
    xgo_age = (now - xgo_ts) if xgo_ts else None
    xgo_on  = (xgo_age is not None and xgo_age <= 5.0)

    inferred_pose = LAST_XGO.get("pose") or _classify_pose(LAST_XGO.get("roll"), LAST_XGO.get("pitch"))
    fw = XGO_FW if XGO_FW != "Null" else None

    yaw = LAST_XGO.get("yaw")
    try: yaw = round(float(yaw), 2) if yaw is not None else None
    except Exception: pass

    bat = LAST_XGO.get("battery")
    # Jednorazowe błyski 0% traktuj jako "brak odczytu".
    if isinstance(bat, (int, float)) and bat == 0 and xgo_on and (last_msg_age is not None and last_msg_age < 2.0):
        bat = None

    devices = {
        "camera": {"on": camera_on, "age_s": (round(cam_age, 3) if cam_age is not None else None),
                   "mode": LAST_CAMERA.get("mode"), "fps": LAST_CAMERA.get("fps")},
        "lcd": {"on": (not ENV_DISABLE_LCD) and (not ENV_NO_DRAW),
                "rot": LAST_CAMERA["lcd"].get("rot", ENV_ROT),
                "no_draw": LAST_CAMERA["lcd"].get("no_draw", ENV_NO_DRAW)},
        "xgo": {"on": xgo_on, "age_s": (round(xgo_age, 3) if xgo_age is not None else None),
                "imu_ok": LAST_XGO.get("imu_ok"), "pose": inferred_pose,
                "battery_pct": bat, "roll": LAST_XGO.get("roll"),
                "pitch": LAST_XGO.get("pitch"), "yaw": yaw, "fw": fw},
    }

    status = "ok"
    if REQUIRE_VISION_HB:
        if (last_hb_age is None) or (last_hb_age > 10.0):
            status = "degraded"

    payload = {
        "status": status,
        "uptime_s": round(now - START_TS, 3),
        "bus": {
            "last_msg_age_s": (round(last_msg_age, 3) if last_msg_age is not None else None),
            "last_heartbeat_age_s": (round(last_hb_age, 3) if last_hb_age is not None else None),
        },
        "devices": devices,
        "state": {
            "present": bool(LAST_STATE.get("present", False)),
            "confidence": float(LAST_STATE.get("confidence", 0.0)),
            "mode": LAST_STATE.get("mode"),
            "age_s": (round(now - LAST_STATE["ts"], 3) if LAST_STATE.get("ts") else None),
        },
    }
    return Response(json.dumps(payload), mimetype="application/json")

def health_alias():
    return jsonify({"ok": True}), 200

def livez():
    # prosty „liveness”: proces żyje i podaje uptime
    up_s = time.time() - START_TS
    return Response(json.dumps({"alive": True, "uptime_s": round(up_s, 3)}), mimetype="application/json")

# === Version / Bus health / Refined readyz ====================================

def _git_info():
    """Spróbuj wyciągnąć commit/describe z gita (best-effort)."""
    try:
        desc = subprocess.check_output(["git", "describe", "--always", "--dirty", "--tags"],
                                       cwd=BASE_DIR, text=True, timeout=1.0).strip()
    except Exception:
        desc = None
    try:
        rev = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                      cwd=BASE_DIR, text=True, timeout=1.0).strip()
    except Exception:
        rev = None
    return {"describe": desc, "commit": rev}

def api_version():
    """
    /api/version — lekka metryka wersji API/aplikacji.
    Zwraca: { name, api, ts, git: {describe, commit} }
    """
    info = _git_info()
    payload = {
        "name": "rider-pi",
        "api": "v2",
        "ts": int(time.time()),
        "git": info,
    }
    return Response(json.dumps(payload), mimetype="application/json")

def api_bus_health():
    """
    /api/bus/health — zdrowie magistrali/telemetrii.
    """
    now = time.time()
    last_msg_age = (now - LAST_MSG_TS) if LAST_MSG_TS else None
    last_hb_age  = (now - LAST_HEARTBEAT_TS) if LAST_HEARTBEAT_TS else None
    payload = {
        "zmq": {"available": bool(_ZMQ_OK)},
        "ports": {"pub": BUS_PUB_PORT, "sub": BUS_SUB_PORT},
        "last_msg_age_s": (round(last_msg_age, 3) if last_msg_age is not None else None),
        "last_heartbeat_age_s": (round(last_hb_age, 3) if last_hb_age is not None else None),
        "ready_hint": (last_msg_age is None) or (last_msg_age < 30.0),
    }
    return Response(json.dumps(payload), mimetype="application/json")

def readyz():
    """
    /readyz — gotowość do obsługi żądań.
    - Jeśli pyzmq nieobecne → ready=True (nie blokujemy startu).
    - Jeśli BUS jest dostępny: gotowe, gdy ostatnia wiadomość nie starsza niż 30s.
    - Zawsze zwraca JSON (nawet gdy pojawi się wyjątek) — bez 500 z tracebackiem.
    """
    try:
        now = time.time()
        # LAST_MSG_TS bywa None lub liczbą; zabezpieczamy rzutowanie:
        last_msg_ts = LAST_MSG_TS
        last_msg_age = (now - float(last_msg_ts)) if last_msg_ts else None

        # Zabezpieczenie na wypadek, gdyby _ZMQ_OK nie był jeszcze w globals()
        zmq_ok = bool(globals().get("_ZMQ_OK", False))

        if not zmq_ok:
            ready = True
        else:
            # brak wiadomości jeszcze po starcie też traktujemy jako "ready"
            ready = (last_msg_age is None) or (last_msg_age < 30.0)

        payload = {
            "ready": bool(ready),
            "last_msg_age_s": (round(last_msg_age, 3) if last_msg_age is not None else None),
            "zmq_available": bool(zmq_ok)
        }
        return Response(json.dumps(payload), mimetype="application/json")
    except Exception as e:
        # awaryjnie: jasny JSON zamiast HTML 500
        err = {"ready": False, "error": str(e)}
        return Response(json.dumps(err), mimetype="application/json", status=500)


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
    """
    Minimalny payload kompatybilny z dawnym skryptem smoke:
    .system.cpu -> {count, percent}
    .devices.summary.flags -> {estop, motion_enable}
    """
    from .system_info import get_sysinfo
    si = get_sysinfo(HIST_CPU, HIST_MEM)
    flags = _read_flags()
    payload = {
        "system": {
            "cpu": {
                "count": os.cpu_count() or 1,
                "percent": si["cpu_pct"],
            }
        },
        "devices": {
            "summary": {
                "flags": flags
            }
        }
    }
    return Response(json.dumps(payload), mimetype="application/json")

# === /api/metrics (JSON kompatybilny ze starym API) ===========================
def api_metrics_alias():
    """
    Zwraca JSON zgodny ze starym API:
      { cpu: {count, percent}, mem: {percent, total, used},
        load: {"1m", "5m", "15m"}, uptime: {boot_time, uptime_s} }
    """
    from .system_info import get_sysinfo
    si = get_sysinfo(HIST_CPU, HIST_MEM)

    # CPU
    cpu = {
        "count": os.cpu_count() or 1,
        "percent": si["cpu_pct"],
    }

    # MEM
    mem = {
        "percent": si["mem"]["pct"],
        "total": si["mem"]["total"],
        "used": si["mem"]["used"],
    }

    # LOAD (klucze jak w starym)
    load = {
        "1m": si["load"]["1"],
        "5m": si["load"]["5"],
        "15m": si["load"]["15"],
    }

    # UPTIME
    try:
        with open("/proc/uptime", "r") as f:
            up_s = float(f.read().split()[0])
    except Exception:
        up_s = max(0.0, time.time() - START_TS)
    boot_time = int(time.time() - up_s)

    uptime = {
        "boot_time": boot_time,
        "uptime_s": up_s,
    }

    payload = {"cpu": cpu, "mem": mem, "load": load, "uptime": uptime}
    return Response(json.dumps(payload), mimetype="application/json")

# === /api/devices (zbiorcza meta) ============================================
def api_devices():
    now = time.time()
    bus = {
        "broker": "unknown",
        "last_seen_ts": (now - ( (now - LAST_MSG_TS) if LAST_MSG_TS else 0)),
    }
    lf_exists = os.path.isfile(RAW_PATH)
    lf_mtime = int(os.stat(RAW_PATH).st_mtime) if lf_exists else None
    vision = {
        "running": (LAST_CAMERA.get("ts") is not None),
        "last_frame": {
            "exists": bool(lf_exists),
            "mtime": lf_mtime,
            # DLA ZGODNOŚCI ZE STARYM API – zawsze raportuj "data/last_frame.jpg"
            "path": "data/last_frame.jpg",
        }
    }
    xgo = {
        "connected": bool(LAST_XGO.get("ts")),
        "last_telemetry_ts": LAST_XGO.get("ts"),
    }
    flags = _read_flags()
    out = {"bus": bus, "vision": vision, "xgo": xgo, "flags": flags}
    return Response(json.dumps(out), mimetype="application/json")

# === /api/last_frame (meta) ===================================================
def api_last_frame():
    exists = os.path.isfile(RAW_PATH)
    mtime = int(os.stat(RAW_PATH).st_mtime) if exists else None
    # dla zgodności ścieżkę raportujemy tak, jak w dawnym API (data/last_frame.jpg),
    # ale realny plik to snapshots/raw.jpg — aplikacje i tak korzystały z /camera/last.
    payload = {"exists": bool(exists), "mtime": mtime, "path": "data/last_frame.jpg"}
    return Response(json.dumps(payload), mimetype="application/json")

# === /api/flags (GET + POST /api/flags/<name>/<on|off>) ======================
def api_flags_get():
    return Response(json.dumps(_read_flags()), mimetype="application/json")

def api_flags_set(name: str, state: str):
    name = name.strip().lower()
    if name not in ("motion.enable", "estop.on"):
        return Response(json.dumps({"ok": False, "error": "unknown flag"}), mimetype="application/json", status=404)
    st = state.strip().lower()
    if st not in ("on", "off"):
        return Response(json.dumps({"ok": False, "error": "bad state"}), mimetype="application/json", status=400)
    ok = _set_flag(name, st == "on")
    return Response(json.dumps({"ok": bool(ok), "name": name, "state": st}), mimetype="application/json", status=(200 if ok else 500))

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
    @stream_with_context
    def gen():
        last_idx = 0
        while True:
            try:
                time.sleep(1.0)
                if last_idx >= len(EVENTS): continue
                for i in range(last_idx, len(EVENTS)):
                    ev = EVENTS[i]
                    yield f"data: {json.dumps(ev)}\n\n"
                last_idx = len(EVENTS)
            except GeneratorExit:
                break
            except Exception:
                time.sleep(0.5)
    return Response(gen(), mimetype='text/event-stream')

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
    """Uruchom odczyt XGO po UART (idempotentnie)."""
    if not ENABLE_XGO_RO:
        print("[api] xgo_ro_loop disabled by ENABLE_XGO_RO=0", flush=True)
        return
    if getattr(start_xgo_ro, "_started", False):
        return
    from . import devices  # local import to avoid circular
    try:
        t = threading.Thread(target=devices.xgo_ro_loop, daemon=True)
        t.start()
        start_xgo_ro._started = True
        print("[api] xgo_ro_loop started", flush=True)
    except Exception as e:
        print("[api] xgo_ro_loop unavailable — skipping", e, flush=True)

# ===== MONKEY-PATCH: /api/control → proxy do :8081/control (POST/OPTIONS) =====
try:
    import requests  # type: ignore
except Exception:
    requests = None

from flask import request, jsonify, make_response

def _api_control_proxy_impl():
    try:
        print("[api] /api/control proxy(v2): method=", request.method, flush=True)

        # CORS preflight
        if request.method == "OPTIONS":
            r = make_response("", 204)
            r.headers["Access-Control-Allow-Origin"]  = "*"
            r.headers["Access-Control-Allow-Headers"] = "Content-Type"
            r.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
            return r

        d = request.get_json(silent=True) or {}
        print("[api] /api/control proxy(v2): body=", d, flush=True)

        # Normalizacja dashboard → payload mostka
        def _f(x, default=0.0):
            try: return float(x)
            except Exception: return float(default)

        payload = None
        typ = (d.get("type") or d.get("action") or "").lower().strip()

        if typ == "drive":
            lx  = _f(d.get("lx", 0.0))
            az  = _f(d.get("az", 0.0))
            dur = _f(d.get("dur", d.get("t", 0.1)), 0.1)
            if dur <= 0.0: dur = 0.10
            payload = {"type":"drive","lx":lx,"az":az,"dur":dur}

        elif typ == "spin":
            dir_  = (d.get("dir") or "").lower()
            speed = _f(d.get("speed", 0.0))
            yaw   = speed if dir_ == "left" else (-speed if dir_ == "right" else 0.0)
            dur   = _f(d.get("dur", 0.3), 0.3)
            payload = {"type":"drive","lx":0.0,"az":yaw,"dur":dur}

        elif typ == "stop":
            payload = {"type":"stop"}

        else:
            # fallback legacy: {"dir":"forward|backward|left|right","v":...,"t":...}
            ddir = (d.get("dir") or "").lower()
            if ddir in ("forward","backward","left","right"):
                v = abs(_f(d.get("v", 0.1), 0.1))
                t = _f(d.get("t", 0.1), 0.1)
                if t <= 0.0: t = 0.10
                vx = +v if ddir=="forward" else (-v if ddir=="backward" else 0.0)
                az = +v if ddir=="left"    else (-v if ddir=="right"    else 0.0)
                payload = {"type":"drive","lx":vx,"az":az,"dur":t}
            else:
                print("[api] /api/control proxy(v2): UNKNOWN ACTION ->", d, flush=True)
                return jsonify({"ok": False, "error": "unknown action (compat-proxy)"}), 400

        if requests is None:
            return jsonify({"ok": False, "error": "requests module missing"}), 500

        rh = requests.post("http://127.0.0.1:8081/control", json=payload, timeout=1.5)
        try:
            body = rh.json()
        except Exception:
            body = {"ok": False, "error": "bad json from web bridge", "status": rh.status_code, "text": rh.text[:300]}

        print("[api] /api/control proxy(v2): →8081 payload=", payload, " status=", rh.status_code, " resp=", body, flush=True)

        r = jsonify(body)
        r.headers["Access-Control-Allow-Origin"]  = "*"
        r.headers["Access-Control-Allow-Headers"] = "Content-Type"
        r.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        return r, rh.status_code

    except Exception as e:
        print("[api] /api/control proxy(v2): ERROR", e, flush=True)
        return jsonify({"ok": False, "error": f"proxy error: {e}"}), 500

# Przeregistruj trasę: usuń wszystkie stare /api/control i dodaj jedną POST/OPTIONS
try:
    to_remove = [r for r in list(app.url_map.iter_rules()) if r.rule == "/api/control"]
    for r in to_remove:
        try:
            app.url_map._rules.remove(r)
            app.url_map._rules_by_endpoint[r.endpoint].remove(r)
        except Exception:
            pass
    app.add_url_rule("/api/control_legacy", endpoint="api_control_legacy", view_func=_api_control_proxy_impl, methods=["POST","OPTIONS"])
    print("[api] /api/control proxy(v2): route installed (POST,OPTIONS)", flush=True)
except Exception as _e:
    print("[api] /api/control proxy(v2): bind failed:", _e, flush=True)
# ===== KONIEC PATCHA =====
