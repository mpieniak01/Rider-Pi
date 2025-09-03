#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rider-Pi – Status API + mini dashboard (Flask 1.x compatible)

Endpoints:
- /                : dashboard (serwowany z web/view.html)
- /control         : sterowanie ruchem (web/control.html)
- /healthz         : status + bus ages + devices (camera/lcd/xgo)
- /health          : prosty alias health
- /state           : last vision.state + blok camera
- /sysinfo         : CPU/MEM/LOAD/DISK/TEMP (+ history dla dashboardu) + OS info
- /metrics         : Prometheus-style, very small set
- /events          : SSE live bus events (vision.*, camera.*, motion.*, cmd.*, motion.bridge.*)
- /camera/last     : ostatnia zapisana klatka (JPEG) lub 404
- /camera/placeholder : SVG komunikat „Brak podglądu (vision wyłączone)”
- /snapshots/<fn>  : bezpieczne serwowanie JPG (cam.jpg, proc.jpg itd.)
- /api/move        : POST {vx,vy,yaw,duration}
- /api/stop        : POST {}
- /api/preset      : POST {name}
- /api/voice       : POST {text}
- /api/cmd         : dowolny JSON → topic 'motion.cmd'
- /pub             : {topic, message:str} → raw publish
- /svc             : LISTA statusów usług z whitelisty
- /svc/<name>/status : status wybranej usługi (vision/last)
- /svc/<name>      : POST {"action":"start|stop|restart|enable|disable"} (przez sudo wrapper)

Zależności: flask, (opcjonalnie) pyzmq; API działa nawet bez ZMQ/XGO.
Testowane na Python 3.9 (RPi OS).
"""

import os, time, json, threading, collections, shutil, subprocess, platform
from flask import (
    Flask, Response, stream_with_context, request,
    send_file, send_from_directory, abort, make_response, jsonify
)
from typing import Optional  # <- dla Python 3.9 (zamiast "str | None")

# --- Konfiguracja ---
BUS_PUB_PORT = int(os.getenv("BUS_PUB_PORT", "5555"))
BUS_SUB_PORT = int(os.getenv("BUS_SUB_PORT", "5556"))
STATUS_API_PORT = int(os.getenv("STATUS_API_PORT", "8080"))

ENV_DISABLE_LCD = (os.getenv("DISABLE_LCD", "0") == "1")
ENV_NO_DRAW     = (os.getenv("NO_DRAW", "0") == "1")
ENV_ROT         = int(os.getenv("PREVIEW_ROT", "0") or 0)

REFRESH_S   = 2.0
HISTORY_LEN = 60  # ~60 punktów, ~1 pkt / sekundę

# Ścieżki: katalog na snapshoty i pliki HTML
BASE_DIR      = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SNAP_DIR      = os.path.abspath(os.getenv("SNAP_DIR", os.path.join(BASE_DIR, "snapshots")))
VIEW_HTML     = os.path.abspath(os.path.join(BASE_DIR, "web", "view.html"))
CONTROL_HTML  = os.path.abspath(os.path.join(BASE_DIR, "web", "control.html"))

# --- Camera/vision paths & flags ---
DATA_DIR        = os.path.abspath(os.path.join(BASE_DIR, "data"))
LAST_FRAME      = os.path.join(DATA_DIR, "last_frame.jpg")   # pojedyncza ostatnia klatka
VISION_ENABLED  = (os.getenv("VISION_ENABLED", "0") == "1")  # off-by-default polityka
LAST_FRESH_S    = float(os.getenv("LAST_FRESH_S", "3"))       # uznaj klatkę za świeżą, jeśli mtime <= X s

# --- Services (whitelist + wrapper) ---
ALLOWED_UNITS = {
    "vision": "rider-vision.service",
    "last":   "rider-last-frame-sink.service",
    "lastframe": "rider-last-frame-sink.service",
}
SERVICE_CTL = os.path.join(BASE_DIR, "ops", "service_ctl.sh")  # sudo wrapper (NOPASSWD)

app = Flask(__name__)

# --- Stan wewnętrzny ---
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
    },
}

# XGO (lekki client read-only)
LAST_XGO = {
    "ts": None,
    "imu_ok": False,
    "pose": None,
    "battery": None,     # %
    "roll": None,
    "pitch": None,
    "yaw": None,
}
XGO_FW = None  # wersja firmware odczytana raz

# historia do wykresu (cpu%, mem%)
HIST_CPU = collections.deque(maxlen=HISTORY_LEN)
HIST_MEM = collections.deque(maxlen=HISTORY_LEN)

# kolejka zdarzeń do /events (SSE)
EVENTS = collections.deque(maxlen=200)

# --- Bezpieczeństwo: ZMQ jest opcjonalne ---
try:
    import zmq  # type: ignore
    _ZMQ_OK = True
except Exception:
    _ZMQ_OK = False

# --- lekki PUB na bus (do wysyłania komend z /api/*) ---
try:
    if _ZMQ_OK:
        _ZMQ_PUB = zmq.Context.instance().socket(zmq.PUB)  # type: ignore
        _ZMQ_PUB.connect(f"tcp://127.0.0.1:{BUS_PUB_PORT}")
    else:
        _ZMQ_PUB = None
except Exception:
    _ZMQ_PUB = None

def bus_pub(topic: str, payload: dict):
    """Wyślij prosty multipart 'topic json' na bus (jeśli pyzmq dostępne)."""
    try:
        if _ZMQ_PUB is None:
            return
        _ZMQ_PUB.send_string(f"{topic} {json.dumps(payload, ensure_ascii=False)}")
    except Exception:
        pass

# --- Narzędzia sysinfo (bez psutil) ---
def _cpu_pct_sample():
    try:
        with open("/proc/stat", "r") as f:
            line = f.readline()
        if not line.startswith("cpu "):
            return 0.0, 0.0
        parts = [float(x) for x in line.split()[1:]]
        idle = parts[3]
        total = sum(parts)
        return idle, total
    except Exception:
        return 0.0, 0.0

_prev = {"idle": None, "total": None}

def cpu_percent():
    idle, total = _cpu_pct_sample()
    if not idle and not total:
        return 0.0
    if _prev["idle"] is None:
        _prev["idle"], _prev["total"] = idle, total
        time.sleep(0.03)
        idle2, total2 = _cpu_pct_sample()
        _prev["idle"], _prev["total"] = idle2, total2
        return 0.0
    diff_idle = idle - _prev["idle"]
    diff_total = total - _prev["total"]
    _prev["idle"], _prev["total"] = idle, total
    if diff_total <= 0:
        return 0.0
    usage = (1.0 - (diff_idle / diff_total)) * 100.0
    return max(0.0, min(100.0, usage))

def load_avg():
    try:
        return os.getloadavg()
    except Exception:
        return (0.0, 0.0, 0.0)

def mem_info():
    total = avail = None
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total = float(line.split()[1]) * 1024.0
                elif line.startswith("MemAvailable:"):
                    avail = float(line.split()[1]) * 1024.0
        if total and avail is not None:
            used = max(0.0, total - avail)
            pct = (used / total) * 100.0
            return {"total": total, "available": avail, "used": used, "pct": pct}
    except Exception:
        pass
    return {"total": 0.0, "available": 0.0, "used": 0.0, "pct": 0.0}

def disk_info(path="/"):
    try:
        du = shutil.disk_usage(path)
        used = du.used
        pct = (used / du.total) * 100.0 if du.total else 0.0
        return {"total": du.total, "used": used, "free": du.free, "pct": pct}
    except Exception:
        return {"total": 0, "used": 0, "free": 0, "pct": 0.0}

def temp_c():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            t = float(f.read().strip()) / 1000.0
            return t
    except Exception:
        pass
    try:
        out = subprocess.check_output(["vcgencmd", "measure_temp"]).decode()
        v = out.strip().split("=")[-1].replace("'C", "").replace("C", "").replace("'", "")
        return float(v)
    except Exception:
        return 0.0

def _os_info():
    pretty = None
    try:
        with open("/etc/os-release") as f:
            kv = {}
            for line in f:
                if "=" in line:
                    k,v = line.strip().split("=",1)
                    kv[k] = v.strip().strip('"')
            pretty = kv.get("PRETTY_NAME")
    except Exception:
        pass
    kernel = platform.release()
    return {"pretty": pretty, "kernel": kernel}

# --- Wątek SUB (bus) ---

def bus_sub_loop():
    """Czyta PUB/SUB: wspiera multipart [topic, payload] oraz single-frame 'topic payload'."""
    global LAST_MSG_TS, LAST_HEARTBEAT_TS, LAST_STATE, LAST_CAMERA
    if not _ZMQ_OK:
        print("[api] pyzmq not available – bus features disabled", flush=True)
        return
    try:
        ctx = zmq.Context.instance()
        sub = ctx.socket(zmq.SUB)
        sub.connect(f"tcp://127.0.0.1:{BUS_SUB_PORT}")
        for t in ("vision.", "camera.", "motion.bridge.", "motion.", "cmd."):
            sub.setsockopt_string(zmq.SUBSCRIBE, t)
        try:
            sub.setsockopt(zmq.RCVTIMEO, 1000)  # 1s timeout
        except Exception:
            pass
        print(f"[api] SUB connected tcp://127.0.0.1:{BUS_SUB_PORT}", flush=True)

        while True:
            try:
                try:
                    parts = sub.recv_multipart(flags=0)
                except zmq.Again:
                    continue

                topic = ""; payload = ""
                if parts:
                    frames = [p.decode("utf-8","ignore") for p in parts]
                    if len(frames) == 1:
                        s1 = frames[0]
                        if " " in s1:
                            topic, payload = s1.split(" ", 1)
                        else:
                            topic, payload = s1, ""
                    else:
                        topic = frames[0]
                        payload = frames[1] if len(frames) == 2 else " ".join(frames[1:])
                else:
                    continue

                LAST_MSG_TS = time.time()
                EVENTS.append({"ts": LAST_MSG_TS, "topic": topic, "data": payload})

                if topic == "vision.dispatcher.heartbeat":
                    LAST_HEARTBEAT_TS = LAST_MSG_TS

                elif topic == "vision.state":
                    try:
                        data = json.loads(payload) if payload else {}
                        LAST_STATE["present"]    = bool(data.get("present", LAST_STATE["present"]))
                        LAST_STATE["confidence"] = float(data.get("confidence", LAST_STATE["confidence"]))
                        if "mode" in data: LAST_STATE["mode"] = data.get("mode")
                        LAST_STATE["ts"]        = float(data.get("ts", LAST_MSG_TS))
                    except Exception:
                        pass

                elif topic == "camera.heartbeat":
                    try:
                        data = json.loads(payload) if payload else {}
                        LAST_CAMERA["ts"]   = LAST_MSG_TS
                        LAST_CAMERA["mode"] = data.get("mode")
                        LAST_CAMERA["fps"]  = data.get("fps")
                        lcd = data.get("lcd") or {}
                        LAST_CAMERA["lcd"].update({
                            "enabled_env": (not ENV_DISABLE_LCD),
                            "no_draw": ENV_NO_DRAW,
                            "rot": ENV_ROT,
                        })
                        for k in ("enabled_env", "no_draw", "rot", "active"):
                            if k in lcd: LAST_CAMERA["lcd"][k] = lcd[k]
                    except Exception:
                        pass
            except Exception:
                time.sleep(0.05)
    except Exception as e:
        print(f"[api] bus_sub_loop error: {e}", flush=True)


def xgo_ro_loop():
    global LAST_XGO, XGO_FW
    try:
        time.sleep(0.5)
        try:
            from tools.xgo_client_ro import XGOClientRO  # type: ignore
        except Exception as e:
            print("[api] xgo_ro_loop import error:", e, flush=True)
            return

        cli = None
        while True:
            try:
                if cli is None:
                    cli = XGOClientRO(port="/dev/ttyAMA0")
                    print("[api] XGO RO connected: /dev/ttyAMA0", flush=True)

                if XGO_FW is None:
                    fw = cli.read_firmware()
                    if fw:
                        XGO_FW = fw

                batt = cli.read_battery()
                roll = cli.read_roll()
                pitch = cli.read_pitch()
                yaw = cli.read_yaw()

                pose = None
                imu_ok = False
                try:
                    imu_ok = (roll is not None and pitch is not None and yaw is not None)
                    if imu_ok:
                        r, p = abs(float(roll)), abs(float(pitch))
                        pose = "upright" if (r < 20 and p < 20) else ("fallen" if (r > 60 or p > 60) else "leaning")
                except Exception:
                    pass

                LAST_XGO.update({
                    "ts": time.time(),
                    "imu_ok": bool(imu_ok),
                    "pose": pose,
                    "battery": int(batt) if batt is not None else None,
                    "roll": float(roll) if roll is not None else None,
                    "pitch": float(pitch) if pitch is not None else None,
                    "yaw": float(yaw) if yaw is not None else None,
                })
                time.sleep(1.0)
            except Exception:
                time.sleep(1.0)
                cli = None
    except Exception as e:
        print(f"[api] xgo_ro_loop error: {e}", flush=True)

# --- Sysinfo parking + historia ---
_last_hist_t = 0.0

def get_sysinfo():
    global _last_hist_t
    ci = cpu_percent()
    la1, la5, la15 = load_avg()
    mi = mem_info()
    di = disk_info("/")
    tc = temp_c()

    now = time.time()
    if now - _last_hist_t >= 1.0:
        HIST_CPU.append(round(ci, 1))
        HIST_MEM.append(round(mi.get("pct", 0.0), 1))
        _last_hist_t = now

    si = {
        "ts": now,
        "cpu_pct": round(ci, 1),
        "load": {"1": round(la1, 2), "5": round(la5, 2), "15": round(la15, 2)},
        "mem": {
            "total": mi["total"], "available": mi["available"],
            "used": mi["used"], "pct": round(mi["pct"], 1)
        },
        "disk": {
            "total": di["total"], "used": di["used"], "free": di["free"], "pct": round(di["pct"], 1)
        },
        "temp_c": round(tc, 1),
        "hist_cpu": list(HIST_CPU),
        "hist_mem": list(HIST_MEM),
        "os": _os_info(),
    }
    if LAST_XGO.get("battery") is not None:
        si["battery_pct"] = int(LAST_XGO["battery"])
    return si

# --- Middleware / nagłówki ---
@app.after_request
def log_and_secure(resp):
    try:
        print(f"[api] {request.method} {request.path}", flush=True)
    except Exception:
        pass
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp

# --- Endpoints JSON ---
@app.route("/healthz")
def healthz():
    now = time.time()
    last_msg_age = (now - LAST_MSG_TS) if LAST_MSG_TS else None
    last_hb_age  = (now - LAST_HEARTBEAT_TS) if LAST_HEARTBEAT_TS else None

    cam_age = (now - LAST_CAMERA["ts"]) if LAST_CAMERA["ts"] else None
    camera_on = (cam_age is not None and cam_age <= 5.0)

    xgo_ts = LAST_XGO.get("ts")
    xgo_age = (now - xgo_ts) if xgo_ts else None
    xgo_ok = (xgo_age is not None and xgo_age <= 5.0)

    devices = {
        "camera": {
            "on": camera_on,
            "age_s": round(cam_age, 3) if cam_age is not None else None,
            "mode": LAST_CAMERA.get("mode"),
            "fps": LAST_CAMERA.get("fps"),
        },
        "lcd": {
            "on": (not ENV_DISABLE_LCD) and (not ENV_NO_DRAW),
            "rot": LAST_CAMERA["lcd"].get("rot", ENV_ROT),
            "no_draw": LAST_CAMERA["lcd"].get("no_draw", ENV_NO_DRAW),
        },
        "xgo": {
            "on": xgo_ok,
            "age_s": round(xgo_age, 3) if xgo_age is not None else None,
            "imu_ok": LAST_XGO.get("imu_ok"),
            "pose": LAST_XGO.get("pose"),
            "battery_pct": LAST_XGO.get("battery"),
            "roll": LAST_XGO.get("roll"),
            "pitch": LAST_XGO.get("pitch"),
            "yaw": LAST_XGO.get("yaw"),
            "fw": XGO_FW,
        },
    }

    status = "ok"
    if (last_msg_age is None) or (last_hb_age is None) or (last_hb_age > 10.0):
        status = "degraded"

    payload = {
        "status": status,
        "uptime_s": round(time.time() - START_TS, 3),
        "bus": {
            "last_msg_age_s": round(last_msg_age, 3) if last_msg_age is not None else None,
            "last_heartbeat_age_s": round(last_hb_age, 3) if last_hb_age is not None else None,
        },
        "devices": devices,
        "state": {
            "present": bool(LAST_STATE.get("present", False)),
            "confidence": float(LAST_STATE.get("confidence", 0.0)),
            "mode": LAST_STATE.get("mode"),
            "age_s": round(now - LAST_STATE["ts"], 3) if LAST_STATE.get("ts") else None,
        }
    }
    return Response(json.dumps(payload), mimetype="application/json")

@app.route("/health")
def health_alias():
    return jsonify({"ok": True}), 200

@app.route("/state")
def state():
    now = time.time()
    ts = LAST_STATE.get("ts")
    age = (now - ts) if ts else None

    has_last = os.path.isfile(LAST_FRAME)
    last_ts = int(os.stat(LAST_FRAME).st_mtime) if has_last else None

    # "vision_enabled": traktuj jako włączone, gdy ENV VISION_ENABLED=1 LUB klatka świeża
    fresh = False
    if last_ts is not None:
        try:
            fresh = (now - float(last_ts)) <= LAST_FRESH_S
        except Exception:
            fresh = False
    vision_enabled = bool(VISION_ENABLED or fresh)

    payload = {
        "present": bool(LAST_STATE.get("present", False)),
        "confidence": float(LAST_STATE.get("confidence", 0.0)),
        "mode": LAST_STATE.get("mode"),
        "ts": ts,
        "age_s": round(age, 3) if age is not None else None,
        "camera": {
            "vision_enabled": vision_enabled,
            "has_last_frame": bool(has_last),
            "last_frame_ts": last_ts,
            "preview_url": f"/camera/last?t={last_ts or int(now)}",
            "placeholder_url": "/camera/placeholder"
        }
    }
    return Response(json.dumps(payload), mimetype="application/json")

@app.route("/sysinfo")
def sysinfo():
    si = get_sysinfo()
    out = {
        "cpu_pct": si["cpu_pct"],
        "load1": si["load"]["1"],
        "load5": si["load"]["5"],
        "load15": si["load"]["15"],
        "mem_total_mb": round(si["mem"]["total"] / 1048576, 1),
        "mem_used_mb": round(si["mem"]["used"] / 1048576, 1),
        "mem_pct": si["mem"]["pct"],
        "disk_total_gb": round(si["disk"]["total"] / 1073741824, 1),
        "disk_used_gb": round(si["disk"]["used"] / 1073741824, 1),
        "disk_pct": si["disk"]["pct"],
        "temp_c": si["temp_c"],
        "hist_cpu": si["hist_cpu"],
        "hist_mem": si["hist_mem"],
        "os_release": ((si["os"].get("pretty") or "—") + " · " + (si["os"].get("kernel") or "—")),
        "ts": si["ts"],
    }
    if "battery_pct" in si and si["battery_pct"] is not None:
        out["battery_pct"] = si["battery_pct"]
    return Response(json.dumps(out), mimetype="application/json")

@app.route("/metrics")
def metrics():
    si = get_sysinfo()
    now = time.time()
    last_msg_age = (now - LAST_MSG_TS) if LAST_MSG_TS else -1
    last_hb_age  = (now - LAST_HEARTBEAT_TS) if LAST_HEARTBEAT_TS else -1
    cam_age = (now - LAST_CAMERA["ts"]) if LAST_CAMERA["ts"] else -1

    # wiek pliku last_frame
    if os.path.isfile(LAST_FRAME):
        try:
            last_ts = os.stat(LAST_FRAME).st_mtime
            last_frame_age = max(0.0, now - float(last_ts))
        except Exception:
            last_frame_age = -1
    else:
        last_frame_age = -1

    xgo_age = -1
    if LAST_XGO.get("ts"):
        xgo_age = now - LAST_XGO["ts"]

    lines = []
    def m(name, val, labels=None):
        if labels:
            lab = ",".join([f'{k}="{v}"' for k,v in labels.items()])
            lines.append(f"{name}{{{lab}}} {val}")
        else:
            lines.append(f"{name} {val}")
    m("rider_cpu_pct", si["cpu_pct"])
    m("rider_mem_pct", si["mem"]["pct"])
    m("rider_disk_pct", si["disk"]["pct"])
    m("rider_temp_c", si["temp_c"])
    if "battery_pct" in si and si["battery_pct"] is not None:
        m("rider_battery_pct", si["battery_pct"])
    m("rider_bus_last_msg_age_seconds", round(last_msg_age,3))
    m("rider_bus_last_heartbeat_age_seconds", round(last_hb_age,3))
    m("rider_camera_last_hb_age_seconds", round(cam_age,3))
    m("rider_camera_last_frame_age_seconds", round(last_frame_age,3))
    m("rider_xgo_last_read_age_seconds", round(xgo_age,3) if xgo_age>=0 else -1)
    return Response("\n".join(lines) + "\n", mimetype="text/plain")

@app.route("/events")
def events():
    @stream_with_context
    def gen():
        last_idx = 0
        while True:
            try:
                time.sleep(1.0)
                if last_idx >= len(EVENTS):
                    continue
                for i in range(last_idx, len(EVENTS)):
                    ev = EVENTS[i]
                    data = json.dumps(ev)
                    yield f"data: {data}\n\n"
                last_idx = len(EVENTS)
            except GeneratorExit:
                break
            except Exception:
                time.sleep(0.5)
    return Response(gen(), mimetype='text/event-stream')

# --- Camera endpoints ---
@app.route("/camera/last", methods=["GET"])
def camera_last():
    if os.path.isfile(LAST_FRAME):
        resp = make_response(send_file(LAST_FRAME, mimetype="image/jpeg"))
        # mocne no-cache (dla przeglądarek i pośredników)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"]        = "no-cache"
        resp.headers["Expires"]       = "0"
        return resp
    return Response(json.dumps({"error": "no_frame"}), mimetype="application/json", status=404)

@app.route("/camera/placeholder", methods=["GET"])
def camera_placeholder():
    svg = """
    <svg xmlns="http://www.w3.org/2000/svg" width="640" height="360">
      <rect width="100%" height="100%" fill="#111"/>
      <text x="50%" y="45%" dominant-baseline="middle" text-anchor="middle"
            font-family="monospace" font-size="20" fill="#ccc">
        Brak podglądu (vision wyłączone)
      </text>
      <text x="50%" y="58%" dominant-baseline="middle" text-anchor="middle"
            font-family="monospace" font-size="12" fill="#777">
        /camera/last zwróci 404, gdy brak klatki
      </text>
    </svg>
    """.strip()
    resp = make_response(svg)
    resp.headers["Content-Type"] = "image/svg+xml"
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp

# --- Services control (systemd whitelist) ---
def _unit_for(name: str) -> Optional[str]:
    if name in ALLOWED_UNITS:
        return ALLOWED_UNITS[name]
    if name in ALLOWED_UNITS.values():
        return name
    return None

def _svc_status(unit: str) -> dict:
    try:
        out = subprocess.check_output(
            ["systemctl", "show", unit, "--no-page",
             "--property=ActiveState,SubState,UnitFileState,LoadState,Description"],
            stderr=subprocess.STDOUT, text=True, timeout=2.0
        )
        kv = {}
        for line in out.splitlines():
            if "=" in line:
                k,v = line.split("=",1)
                kv[k.strip()] = v.strip()
        return {
            "unit": unit,
            "load": kv.get("LoadState"),
            "active": kv.get("ActiveState"),
            "sub": kv.get("SubState"),
            "enabled": kv.get("UnitFileState"),
            "desc": kv.get("Description"),
        }
    except Exception as e:
        return {"unit": unit, "error": str(e)}

@app.route("/svc", methods=["GET"])
def svc_list():
    out = []
    for unit in sorted(set(ALLOWED_UNITS.values())):
        out.append(_svc_status(unit))
    return Response(json.dumps({"services": out}), mimetype="application/json")

@app.route("/svc/<name>/status", methods=["GET"])
def svc_status(name: str):
    unit = _unit_for(name)
    if not unit:
        return Response(json.dumps({"error":"unknown service"}), mimetype="application/json", status=404)
    return Response(json.dumps(_svc_status(unit)), mimetype="application/json")

@app.route("/svc/<name>", methods=["POST"])
def svc_action(name: str):
    """
    Body: {"action":"start|stop|restart|enable|disable"}
    Wykonuje przez sudo ops/service_ctl.sh (wymaga NOPASSWD dla tego skryptu).
    """
    unit = _unit_for(name)
    if not unit:
        return Response(json.dumps({"error":"unknown service"}), mimetype="application/json", status=404)
    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").lower()
    if action not in ("start","stop","restart","enable","disable"):
        return Response(json.dumps({"error":"bad action"}), mimetype="application/json", status=400)

    if not os.path.isfile(SERVICE_CTL) or not os.access(SERVICE_CTL, os.X_OK):
        return Response(
            json.dumps({"error":"service_ctl_missing",
                        "hint":"chmod +x ops/service_ctl.sh & add sudoers NOPASSWD"}),
            mimetype="application/json", status=501
        )
    try:
        proc = subprocess.run(
            ["sudo", "-n", SERVICE_CTL, unit, action],
            check=False, capture_output=True, text=True, timeout=8.0
        )
        status = _svc_status(unit)
        return Response(json.dumps({
            "ok": (proc.returncode == 0),
            "rc": proc.returncode,
            "stdout": (proc.stdout or "")[-4000:],
            "stderr": (proc.stderr or "")[-4000:],
            "status": status
        }), mimetype="application/json", status=(200 if proc.returncode==0 else 500))
    except subprocess.TimeoutExpired:
        return Response(json.dumps({"error":"timeout"}), mimetype="application/json", status=504)
    except Exception as e:
        return Response(json.dumps({"error": str(e)}), mimetype="application/json", status=500)

# --- Dashboard / Control ---
@app.route("/")
def dashboard():
    if not os.path.isfile(VIEW_HTML):
        return Response("<h1>view.html missing</h1>", mimetype="text/html"), 404
    return send_file(VIEW_HTML)

@app.route("/control")
def control_page():
    if not os.path.isfile(CONTROL_HTML):
        return Response("<h1>control.html missing</h1>", mimetype="text/html"), 404
    return send_file(CONTROL_HTML)

# --- API sterowania ---
@app.route("/api/move", methods=["POST"])
def api_move():
    data = request.get_json(silent=True) or {}
    vx  = float(data.get("vx", 0.0))
    vy  = float(data.get("vy", 0.0))
    yaw = float(data.get("yaw", 0.0))
    duration = float(data.get("duration", 0.0))
    bus_pub("cmd.move", {"vx": vx, "vy": vy, "yaw": yaw, "duration": duration, "ts": time.time()})
    return Response(json.dumps({"ok": True}), mimetype="application/json")

@app.route("/api/stop", methods=["POST"])
def api_stop():
    bus_pub("cmd.stop", {"ts": time.time()})
    return Response(json.dumps({"ok": True}), mimetype="application/json")

@app.route("/api/preset", methods=["POST"])
def api_preset():
    name = (request.get_json(silent=True) or {}).get("name")
    bus_pub("cmd.preset", {"name": name, "ts": time.time()})
    return Response(json.dumps({"ok": True}), mimetype="application/json")

@app.route("/api/voice", methods=["POST"])
def api_voice():
    text = (request.get_json(silent=True) or {}).get("text", "")
    bus_pub("cmd.voice", {"text": text, "ts": time.time()})
    return Response(json.dumps({"ok": True}), mimetype="application/json")

@app.route("/api/cmd", methods=["POST"])
def api_cmd():
    """
    - drive: cmd.move {vx, yaw, duration}
    - stop : cmd.stop {}
    - spin : cmd.move {vx:0, yaw:±speed, duration:dur}
    """
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return Response(json.dumps({"error":"JSON object expected"}), mimetype="application/json", status=400)

    t = (data.get("type") or "").lower()
    ts = time.time()

    try:
        if t == "drive":
            vx  = float(data.get("lx") or data.get("vx") or 0.0)
            yaw = float(data.get("az") or data.get("yaw") or 0.0)
            dur = float(data.get("dur") or data.get("duration") or 0.0)
            bus_pub("cmd.move", {"vx": vx, "yaw": yaw, "duration": dur, "ts": ts})
            return Response(json.dumps({"ok": True}), mimetype="application/json")

        if t == "stop":
            bus_pub("cmd.stop", {"ts": ts})
            return Response(json.dumps({"ok": True}), mimetype="application/json")

        if t == "spin":
            dir_ = (data.get("dir") or "").lower()
            speed = float(data.get("speed") or 0.3)
            dur   = float(data.get("dur") or data.get("duration") or 0.45)
            yaw   = -abs(speed) if dir_ == "left" else +abs(speed)
            bus_pub("cmd.move", {"vx": 0.0, "yaw": yaw, "duration": dur, "ts": ts})
            return Response(json.dumps({"ok": True}), mimetype="application/json")

        bus_pub("cmd.raw", {"payload": data, "ts": ts})
        return Response(json.dumps({"ok": True, "note": "unknown type -> cmd.raw"}), mimetype="application/json")

    except Exception as e:
        return Response(json.dumps({"error": str(e)}), mimetype="application/json", status=500)

# --- RAW publish ---
@app.route("/pub", methods=["POST"])
def api_pub_generic():
    data = request.get_json(silent=True) or {}
    topic = data.get("topic")
    message = data.get("message")
    if not topic or message is None:
        return Response(json.dumps({"error":"need {topic, message}"}), mimetype="application/json", status=400)
    if not isinstance(message, str):
        message = json.dumps(message, ensure_ascii=False)

    if _ZMQ_OK and _ZMQ_PUB is not None:
        _ZMQ_PUB.send_string(f"{topic} {message}")
        return Response(json.dumps({"ok": True}), mimetype="application/json")
    else:
        return Response(json.dumps({"error":"bus not available"}), mimetype="application/json", status=503)

# --- Serwowanie snapshotów ---
@app.route("/snapshots/<path:fname>")
def snapshots_static(fname: str):
    safe = os.path.abspath(os.path.join(SNAP_DIR, fname))
    if not safe.startswith(SNAP_DIR):
        return abort(403)
    if not os.path.isfile(safe):
        return abort(404)
    return send_from_directory(SNAP_DIR, fname, cache_timeout=0)

# --- Start ---
START_TS = time.time()

def start_bus_sub():
    if _ZMQ_OK:
        t = threading.Thread(target=bus_sub_loop, daemon=True)
        t.start()
        print("[api] bus_sub_loop started", flush=True)
    else:
        print("[api] bus_sub_loop unavailable or pyzmq missing — skipping", flush=True)

def start_xgo_ro():
    try:
        t = threading.Thread(target=xgo_ro_loop, daemon=True)
        t.start()
        print("[api] xgo_ro_loop started", flush=True)
    except Exception as e:
        print("[api] xgo_ro_loop unavailable — skipping", e, flush=True)

if __name__ == "__main__":
    try:
        os.makedirs(SNAP_DIR, exist_ok=True)
        os.makedirs(DATA_DIR, exist_ok=True)
    except Exception:
        pass
    start_bus_sub()
    start_xgo_ro()
    app.run(host="0.0.0.0", port=STATUS_API_PORT, threaded=True)

