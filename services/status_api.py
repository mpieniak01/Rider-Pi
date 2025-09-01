#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rider-Pi – Status API + mini dashboard (Flask 1.x compatible)

Endpoints:
- /                : dashboard (serwowany z web/view.html)
- /control         : sterowanie ruchem (web/control.html)
- /healthz         : status + bus ages + devices (camera/lcd/xgo)
- /state           : last vision.state
- /sysinfo         : CPU/MEM/LOAD/DISK/TEMP (+ history dla dashboardu) + OS info
- /metrics         : Prometheus-style, very small set
- /events          : SSE live bus events (vision.*, camera.*, motion.*, cmd.*, motion.bridge.*)
- /snapshots/<fn>  : bezpieczne serwowanie JPG (cam.jpg, proc.jpg itd.)
- /api/move        : POST {vx,vy,yaw,duration}
- /api/stop        : POST {}
- /api/preset      : POST {name}
- /api/voice       : POST {text}
- /api/cmd         : NOWE – dowolny JSON → topic 'motion.cmd'
- /pub             : NOWE – {topic, message:str} → raw publish

Zależności: flask, (opcjonalnie) pyzmq; API działa nawet bez ZMQ/XGO.
Testowane na Python 3.9 (RPi OS).
"""

import os, time, json, threading, collections, shutil, subprocess, platform
from flask import Flask, Response, stream_with_context, request, send_file, send_from_directory, abort

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

app = Flask(__name__)

# --- Stan wewnętrzny ---
LAST_MSG_TS = None
LAST_HEARTBEAT_TS = None
# trzymamy też mode (jeśli dispatcher publikuje)
LAST_STATE = {"present": False, "confidence": 0.0, "mode": None, "ts": None}

LAST_CAMERA = {  # aktualizowane z camera.heartbeat
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
            return {
                "total": total, "available": avail,
                "used": used, "pct": pct,
            }
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
    global LAST_MSG_TS, LAST_HEARTBEAT_TS, LAST_STATE, LAST_CAMERA
    if not _ZMQ_OK:
        print("[api] pyzmq not available – bus features disabled", flush=True)
        return
    try:
        ctx = zmq.Context.instance()
        sub = ctx.socket(zmq.SUB)
        sub.connect(f"tcp://127.0.0.1:{BUS_SUB_PORT}")
        # Słuchamy dotychczasowych i dodajemy ruch/cmd:
        for t in ("vision.", "camera.", "motion.bridge.", "motion.", "cmd."):
            sub.setsockopt_string(zmq.SUBSCRIBE, t)
        print(f"[api] SUB connected tcp://127.0.0.1:{BUS_SUB_PORT}", flush=True)

        while True:
            try:
                msg = sub.recv_string()
                LAST_MSG_TS = time.time()
                topic, payload = msg.split(" ", 1) if " " in msg else (msg, "")
                EVENTS.append({"ts": LAST_MSG_TS, "topic": topic, "data": payload})

                if topic == "vision.dispatcher.heartbeat":
                    LAST_HEARTBEAT_TS = LAST_MSG_TS

                elif topic == "vision.state":
                    # scalamy present/confidence/mode/ts
                    try:
                        data = json.loads(payload)
                        LAST_STATE["present"]    = bool(data.get("present", LAST_STATE["present"]))
                        LAST_STATE["confidence"] = float(data.get("confidence", LAST_STATE["confidence"]))
                        if "mode" in data:
                            LAST_STATE["mode"] = data.get("mode")
                        LAST_STATE["ts"]        = float(data.get("ts", LAST_MSG_TS))
                    except Exception:
                        pass

                elif topic == "camera.heartbeat":
                    try:
                        data = json.loads(payload)
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
                            if k in lcd:
                                LAST_CAMERA["lcd"][k] = lcd[k]
                    except Exception:
                        pass
            except Exception:
                time.sleep(0.05)
    except Exception as e:
        print(f"[api] bus_sub_loop error: {e}", flush=True)

# --- XGO read-only loop ---
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

@app.route("/state")
def state():
    now = time.time()
    ts = LAST_STATE.get("ts")
    age = (now - ts) if ts else None
    payload = {
        "present": bool(LAST_STATE.get("present", False)),
        "confidence": float(LAST_STATE.get("confidence", 0.0)),
        "mode": LAST_STATE.get("mode"),
        "ts": ts,
        "age_s": round(age, 3) if age is not None else None,
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

# --- Dashboard (zewnętrzny plik HTML) ---
@app.route("/")
def dashboard():
    if not os.path.isfile(VIEW_HTML):
        return Response("<h1>view.html missing</h1>", mimetype="text/html"), 404
    return send_file(VIEW_HTML)

# --- Control (zewnętrzny plik HTML) ---
@app.route("/control")
def control_page():
    if not os.path.isfile(CONTROL_HTML):
        return Response("<h1>control.html missing</h1>", mimetype="text/html"), 404
    return send_file(CONTROL_HTML)

# --- API sterowania (wysyłamy komendy na bus; egzekucja po stronie motion_bridge) ---
@app.route("/api/move", methods=["POST"])
def api_move():
    data = request.get_json(silent=True) or {}
    vx  = float(data.get("vx", 0.0))
    vy  = float(data.get("vy", 0.0))
    yaw = float(data.get("yaw", 0.0))
    duration = float(data.get("duration", 0.0))
    # zgodnie z dotychczasowym mostem – publikujemy na 'cmd.move'
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

# --- NOWE: ogólny endpoint komend JSON -> motion.cmd ---
@app.route("/api/cmd", methods=["POST"])
def api_cmd():
    """
    Prosta, kompatybilna mapa:
      - drive: cmd.move {vx, yaw, duration}
      - stop : cmd.stop {}
      - spin : cmd.move {vx:0, yaw:±speed, duration:dur}
    Bez żadnych dodatkowych topiców — to co już działało w Twoim bridge.
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

        # fallback: pokaż do debug
        bus_pub("cmd.raw", {"payload": data, "ts": ts})
        return Response(json.dumps({"ok": True, "note": "unknown type -> cmd.raw"}), mimetype="application/json")

    except Exception as e:
        return Response(json.dumps({"error": str(e)}), mimetype="application/json", status=500)



# --- NOWE: uniwersalny publish {topic, message:str} ---
@app.route("/pub", methods=["POST"])
def api_pub_generic():
    data = request.get_json(silent=True) or {}
    topic = data.get("topic")
    message = data.get("message")
    if not topic or message is None:
        return Response(json.dumps({"error":"need {topic, message}"}), mimetype="application/json", status=400)
    # message jako string (jeśli nie string – serializujemy)
    if not isinstance(message, str):
        message = json.dumps(message, ensure_ascii=False)
    bus_pub(topic, {"_raw": message}) if False else _ZMQ_PUB.send_string(f"{topic} {message}")  # raw publish
    return Response(json.dumps({"ok": True}), mimetype="application/json")

# --- Serwowanie snapshotów (cam.jpg / proc.jpg itd.) ---
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
    except Exception:
        pass
    start_bus_sub()
    start_xgo_ro()
    

# --- added: hard alias /health for final running app ---
try:
    from flask import jsonify
    if hasattr(app, "add_url_rule"):
        app.add_url_rule(
            "/health",
            endpoint="__rp_health_alias",
            view_func=lambda: (jsonify({"ok": True}), 200),
            methods=["GET"],
        )
except Exception as _e:
    # nie blokuj startu serwera
    pass
# --- end added ---
app.run(host="0.0.0.0", port=STATUS_API_PORT, threaded=True)

# --- added by reorg fix ---
try:
    from flask import jsonify
except Exception:
    pass

@app.route("/health")
def _health():
    # Prosty check: API żyje
    return jsonify({"ok": True}), 200
