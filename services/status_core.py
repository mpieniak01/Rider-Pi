#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rider-Pi – Status API + mini dashboard (Flask 1.x compatible)

Zmiany (2025-09-04):
- Port: obsługa obu zmiennych środowiskowych (STATUS_API_PORT i API_PORT).
- /healthz: flaga REQUIRE_VISION_HEARTBEAT (ENV) – domyślnie WYŁ. (0).
- Sanityzacja XGO: yaw → [-180, 180]; fw: "Null"/"null"/""/"none"/"0" -> None.
- /camera/placeholder akceptuje HEAD.
- "/" fallback gdy brak web/view.html.
- Inferencja pose na bazie roll/pitch gdy pose==None.
- Nie nadpisuj niezerowych roll/pitch/yaw wartością 0.0 z mostka.
- Routing odseparowany (register_routes).
- Bateria: przyjmujemy % / ułamek 0–1 / napięcie (2S/3S) → %.
- BUS: obsługa `xgo.*`, `devices.xgo.*`, `motion.bridge.telemetry` i `motion.bridge.battery_pct`.
- UART: wiele getterów bat/fw, konwersja napięcia.
"""

import os, time, json, threading, collections, shutil, subprocess, platform
from flask import (
    Flask, Response, stream_with_context, request,
    send_file, send_from_directory, abort, make_response, jsonify
)
from typing import Optional, Callable

# --- Konfiguracja ---
BUS_PUB_PORT = int(os.getenv("BUS_PUB_PORT", "5555"))
BUS_SUB_PORT = int(os.getenv("BUS_SUB_PORT", "5556"))
STATUS_API_PORT = int(os.getenv("STATUS_API_PORT") or os.getenv("API_PORT") or "8080")
REQUIRE_VISION_HB = (os.getenv("REQUIRE_VISION_HEARTBEAT", "0") == "1")

ENV_DISABLE_LCD = (os.getenv("DISABLE_LCD", "0") == "1")
ENV_NO_DRAW     = (os.getenv("NO_DRAW", "0") == "1")
ENV_ROT         = int(os.getenv("PREVIEW_ROT", "0") or 0)

REFRESH_S   = 2.0
HISTORY_LEN = 60

# Ścieżki
BASE_DIR      = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SNAP_DIR      = os.path.abspath(os.getenv("SNAP_DIR") or os.getenv("SNAP_BASE") or os.path.join(BASE_DIR, "snapshots"))
VIEW_HTML     = os.path.abspath(os.path.join(BASE_DIR, "web", "view.html"))
CONTROL_HTML  = os.path.abspath(os.path.join(BASE_DIR, "web", "control.html"))
RAW_PATH  = os.path.join(SNAP_DIR, "raw.jpg")
PROC_PATH = os.path.join(SNAP_DIR, "proc.jpg")

# Camera/vision
DATA_DIR        = os.path.abspath(os.path.join(BASE_DIR, "data"))
VISION_ENABLED  = (os.getenv("VISION_ENABLED", "0") == "1")
LAST_FRESH_S    = float(os.getenv("LAST_FRESH_S", "3"))

# Services (whitelist)
ALLOWED_UNITS = {
    "vision": "rider-vision.service",
    "last":   "rider-ssd-preview.service",
    "lastframe": "rider-ssd-preview.service",
    "xgo": "rider-motion-bridge.service",
}
SERVICE_CTL = os.path.join(BASE_DIR, "ops", "service_ctl.sh")

app = Flask(__name__)

# --- Stan wewnętrzny ---
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

# --- ZMQ opcjonalnie ---
try:
    import zmq  # type: ignore
    _ZMQ_OK = True
except Exception:
    _ZMQ_OK = False

try:
    if _ZMQ_OK:
        _ZMQ_PUB = zmq.Context.instance().socket(zmq.PUB)  # type: ignore
        _ZMQ_PUB.connect(f"tcp://127.0.0.1:{BUS_PUB_PORT}")
    else:
        _ZMQ_PUB = None
except Exception:
    _ZMQ_PUB = None

def bus_pub(topic: str, payload: dict):
    try:
        if _ZMQ_PUB is None:
            return
        _ZMQ_PUB.send_string(f"{topic} {json.dumps(payload, ensure_ascii=False)}")
    except Exception:
        pass

# --- Sysinfo helpers ---
def _cpu_pct_sample():
    try:
        with open("/proc/stat", "r") as f:
            line = f.readline()
        if not line.startswith("cpu "):
            return 0.0, 0.0
        parts = [float(x) for x in line.split()[1:]]
        idle = parts[3]; total = sum(parts)
        return idle, total
    except Exception:
        return 0.0, 0.0

_prev = {"idle": None, "total": None}
def cpu_percent():
    idle, total = _cpu_pct_sample()
    if not idle and not total: return 0.0
    if _prev["idle"] is None:
        _prev["idle"], _prev["total"] = idle, total
        time.sleep(0.03)
        idle2, total2 = _cpu_pct_sample()
        _prev["idle"], _prev["total"] = idle2, total2
        return 0.0
    diff_idle = idle - _prev["idle"]; diff_total = total - _prev["total"]
    _prev["idle"], _prev["total"] = idle, total
    if diff_total <= 0: return 0.0
    usage = (1.0 - (diff_idle / diff_total)) * 100.0
    return max(0.0, min(100.0, usage))

def load_avg():
    try: return os.getloadavg()
    except Exception: return (0.0, 0.0, 0.0)

def mem_info():
    total = avail = None
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal:"): total = float(line.split()[1]) * 1024.0
                elif line.startswith("MemAvailable:"): avail = float(line.split()[1]) * 1024.0
        if total and avail is not None:
            used = max(0.0, total - avail); pct = (used / total) * 100.0
            return {"total": total, "available": avail, "used": used, "pct": pct}
    except Exception:
        pass
    return {"total": 0.0, "available": 0.0, "used": 0.0, "pct": 0.0}

def disk_info(path="/"):
    try:
        du = shutil.disk_usage(path)
        used = du.used; pct = (used / du.total) * 100.0 if du.total else 0.0
        return {"total": du.total, "used": used, "free": du.free, "pct": pct}
    except Exception:
        return {"total": 0, "used": 0, "free": 0, "pct": 0.0}

def temp_c():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return float(f.read().strip()) / 1000.0
    except Exception:
        pass
    try:
        out = subprocess.check_output(["vcgencmd", "measure_temp"]).decode()
        v = out.strip().split("=")[-1].replace("'C","").replace("C","").replace("'","")
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
    return {"pretty": pretty, "kernel": platform.release()}

# --- Sanityzacje XGO / bateria ---
def _sanitize_fw(v):
    if v is None: return None
    s = str(v).strip()
    return None if s.lower() in ("null", "", "none", "0") else s

def _voltage_to_pct(v: float) -> Optional[int]:
    """Heurystyka: napięcie 2S (6.4–8.4V) lub 3S (9.6–12.6V) -> %."""
    try: vf = float(v)
    except Exception: return None
    if 9.3 <= vf <= 12.9:     # 3S
        v_min, v_max = 9.6, 12.6
    elif 6.0 <= vf <= 8.7:    # 2S
        v_min, v_max = 6.4, 8.4
    else:
        return None
    pct = (vf - v_min) / (v_max - v_min) * 100.0
    return int(max(0, min(100, round(pct))))

def _coerce_batt_like(v) -> Optional[int]:
    """Akceptuj % (1..100), ułamek (0..1], napięcie (6–13V)."""
    if v is None: return None
    try: f = float(v)
    except Exception: return None
    if 0.0 < f <= 1.0:   # ułamek
        return int(round(f * 100.0))
    if 1.0 < f <= 100.0: # procent
        return int(round(f))
    return _voltage_to_pct(f)

def _sanitize_batt(v):
    """Zwraca int 0–100 lub None."""
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

# --- BUS helpers / odbiór ---
def _json_or_raw(payload: str):
    try:
        return json.loads(payload) if payload not in (None, "") else None
    except Exception:
        s = (payload or "").strip()
        if s == "": return None
        try:
            if "." in s or "e" in s.lower(): return float(s)
            return int(s)
        except Exception:
            pass
        if "," in s and not s.startswith("{") and not s.startswith("["):
            parts = [p.strip() for p in s.split(",")]
            out = []
            for p in parts:
                try:
                    if "." in p or "e" in p.lower(): out.append(float(p))
                    else: out.append(int(p))
                except Exception:
                    out.append(p)
            return out
        return s

def _update_xgo_from_dict(d: dict):
    """Scal słownik telemetry XGO do LAST_XGO (nie nadpisuj pose=None)."""
    global XGO_FW
    if not isinstance(d, dict): return
    ts = float(d.get("ts") or time.time())
    LAST_XGO["ts"] = ts

    if "imu_ok" in d: LAST_XGO["imu_ok"] = bool(d.get("imu_ok"))
    if "pose" in d and d.get("pose") is not None:
        LAST_XGO["pose"] = d.get("pose")

    bat = d.get("battery_pct", d.get("battery"))
    bat = _sanitize_batt(bat) if bat is not None else None
    if bat is not None: LAST_XGO["battery"] = bat

    for k in ("roll","pitch","yaw"):
        if k in d and d.get(k) is not None:
            try:
                val = float(d.get(k))
                if k == "yaw": val = _norm_angle180(val)
                prev = LAST_XGO.get(k)
                if (val == 0.0) and (prev not in (None, 0.0)):
                    pass
                else:
                    LAST_XGO[k] = val
            except Exception:
                LAST_XGO[k] = d.get(k)

    fw = _sanitize_fw(d.get("fw"))
    if fw is not None:
        XGO_FW = fw

def _decode_frames(frames):
    if not frames: return "", ""
    if len(frames) == 1:
        s = frames[0]
        return (s.split(" ", 1) + [""])[:2] if " " in s else (s, "")
    topic = frames[0]
    payload = frames[1] if len(frames) == 2 else " ".join(frames[1:])
    return topic, payload

def bus_sub_loop():
    global LAST_MSG_TS, LAST_HEARTBEAT_TS, LAST_STATE, LAST_CAMERA, LAST_XGO, XGO_FW
    if not _ZMQ_OK:
        print("[api] pyzmq not available – bus features disabled", flush=True)
        return
    try:
        ctx = zmq.Context.instance()
        sub = ctx.socket(zmq.SUB)
        sub.connect(f"tcp://127.0.0.1:{BUS_SUB_PORT}")
        for t in ("vision.", "camera.", "motion.bridge.", "motion.", "cmd.", "devices.", "xgo."):
            sub.setsockopt_string(zmq.SUBSCRIBE, t)
        try: sub.setsockopt(zmq.RCVTIMEO, 1000)
        except Exception: pass
        print(f"[api] SUB connected tcp://127.0.0.1:{BUS_SUB_PORT}", flush=True)

        while True:
            try:
                try:
                    parts_bin = sub.recv_multipart(flags=0)
                except zmq.Again:
                    continue
                frames = [p.decode("utf-8", "ignore") for p in parts_bin]
                topic, payload = _decode_frames(frames)

                LAST_MSG_TS = time.time()
                EVENTS.append({"ts": LAST_MSG_TS, "topic": topic, "data": payload})

                if topic == "vision.dispatcher.heartbeat":
                    LAST_HEARTBEAT_TS = LAST_MSG_TS
                    continue

                # devices.xgo.*
                if topic.startswith("devices.xgo"):
                    suffix = topic[len("devices.xgo"):].lstrip(".")
                    data = _json_or_raw(payload)
                    if suffix == "" and isinstance(data, dict):
                        _update_xgo_from_dict(data)
                    else:
                        LAST_XGO["ts"] = LAST_MSG_TS
                        if suffix == "pose":
                            if data not in (None, "", []): LAST_XGO["pose"] = data
                        elif suffix in ("battery","battery_pct"):
                            b = _sanitize_batt(data) if data is not None else None
                            if b is not None: LAST_XGO["battery"] = b
                        elif suffix in ("roll","pitch","yaw"):
                            try:
                                v = float(data) if data is not None else None
                                if v is not None:
                                    if suffix == "yaw": v = _norm_angle180(v)
                                    prev = LAST_XGO.get(suffix)
                                    if (v == 0.0) and (prev not in (None, 0.0)):
                                        pass
                                    else:
                                        LAST_XGO[suffix] = v
                            except Exception:
                                LAST_XGO[suffix] = data
                        elif suffix == "imu_ok":
                            LAST_XGO["imu_ok"] = bool(data)
                        elif suffix == "fw":
                            fw = _sanitize_fw(data)
                            if fw is not None: XGO_FW = fw
                        elif isinstance(data, dict):
                            _update_xgo_from_dict(data)
                    continue

                # xgo.*
                if topic.startswith("xgo."):
                    suffix = topic[len("xgo."):].lstrip(".")
                    data = _json_or_raw(payload)
                    LAST_XGO["ts"] = LAST_MSG_TS
                    if suffix == "pose":
                        if data not in (None, "", []): LAST_XGO["pose"] = data
                    elif suffix in ("battery","battery_pct"):
                        b = _sanitize_batt(data) if data is not None else None
                        if b is not None: LAST_XGO["battery"] = b
                    elif suffix in ("roll","pitch","yaw"):
                        try:
                            v = float(data) if data is not None else None
                            if v is not None:
                                if suffix == "yaw": v = _norm_angle180(v)
                                prev = LAST_XGO.get(suffix)
                                if (v == 0.0) and (prev not in (None, 0.0)):
                                    pass
                                else:
                                    LAST_XGO[suffix] = v
                        except Exception:
                            LAST_XGO[suffix] = data
                    elif suffix == "imu_ok":
                        LAST_XGO["imu_ok"] = bool(data)
                    elif suffix == "fw":
                        fw = _sanitize_fw(data)
                        if fw is not None: XGO_FW = fw
                    elif isinstance(data, dict):
                        _update_xgo_from_dict(data)
                    continue

                # motion.bridge telemetry (JSON)
                if topic.startswith("motion.bridge.telemetry"):
                    try:
                        d = json.loads(payload) if payload else {}
                        _update_xgo_from_dict(d)
                    except Exception:
                        pass
                    continue

                # motion.bridge.battery_pct (wartość pojedyncza)
                if topic == "motion.bridge.battery_pct":
                    b = _sanitize_batt(_json_or_raw(payload))
                    if b is not None:
                        LAST_XGO["ts"] = LAST_MSG_TS
                        LAST_XGO["battery"] = b
                    continue

                if topic == "vision.state":
                    try:
                        data = json.loads(payload) if payload else {}
                        LAST_STATE["present"]    = bool(data.get("present", LAST_STATE["present"]))
                        LAST_STATE["confidence"] = float(data.get("confidence", LAST_STATE["confidence"]))
                        if "mode" in data: LAST_STATE["mode"] = data.get("mode")
                        LAST_STATE["ts"] = float(data.get("ts", LAST_MSG_TS))
                    except Exception:
                        pass
                    continue

                if topic == "camera.heartbeat":
                    try:
                        data = json.loads(payload) if payload else {}
                        LAST_CAMERA["ts"]   = LAST_MSG_TS
                        LAST_CAMERA["mode"] = data.get("mode")
                        LAST_CAMERA["fps"]  = data.get("fps")
                        lcd = data.get("lcd") or {}
                        LAST_CAMERA["lcd"].update({"enabled_env": (not ENV_DISABLE_LCD), "no_draw": ENV_NO_DRAW, "rot": ENV_ROT})
                        for k in ("enabled_env","no_draw","rot","active"):
                            if k in lcd: LAST_CAMERA["lcd"][k] = lcd[k]
                    except Exception:
                        pass
                    continue

            except Exception:
                time.sleep(0.05)
    except Exception as e:
        print(f"[api] bus_sub_loop error: {e}", flush=True)

# --- UART RO ---
def xgo_ro_loop():
    global LAST_XGO, XGO_FW
    try:
        time.sleep(0.5)
        try:
            from tools.xgo_client_ro import XGOClientRO  # type: ignore
        except Exception as e:
            print("[api] xgo_ro_loop import error:", e, flush=True)
            return

        def _try_battery(cli):
            getters = [
                ("pct", getattr(cli, "read_battery_pct", None)),
                ("pct", getattr(cli, "get_battery_pct", None)),
                ("pct", getattr(cli, "battery_pct", None)),
                ("raw", getattr(cli, "read_battery", None)),
                ("raw", getattr(cli, "get_battery", None)),
                ("volt", getattr(cli, "read_voltage", None)),
                ("volt", getattr(cli, "get_voltage", None)),
                ("volt", getattr(cli, "voltage", None)),
            ]
            for kind, fn in getters:
                if not callable(fn): continue
                try: val = fn()
                except Exception: continue
                if val is None: continue
                if kind == "pct":
                    pct = _sanitize_batt(val)
                elif kind == "volt":
                    pct = _voltage_to_pct(val)
                else:
                    pct = _sanitize_batt(val)
                if pct is not None:
                    return pct
            return None

        def _try_fw(cli):
            fns = [
                getattr(cli, "read_firmware", None),
                getattr(cli, "get_firmware", None),
                getattr(cli, "read_version", None),
                getattr(cli, "get_version", None),
            ]
            for fn in fns:
                if not callable(fn): continue
                try:
                    v = _sanitize_fw(fn())
                    if v: return v
                except Exception:
                    pass
            return None

        cli = None
        while True:
            try:
                if cli is None:
                    cli = XGOClientRO(port="/dev/ttyAMA0")
                    print("[api] XGO RO connected: /dev/ttyAMA0", flush=True)

                if XGO_FW is None:
                    fw = _try_fw(cli)
                    if fw: XGO_FW = fw

                batt_pct = _try_battery(cli)

                roll = cli.read_roll()  if hasattr(cli, "read_roll")  else None
                pitch= cli.read_pitch() if hasattr(cli, "read_pitch") else None
                yaw_r= cli.read_yaw()   if hasattr(cli, "read_yaw")   else None
                yaw  = _norm_angle180(yaw_r) if yaw_r is not None else None

                pose = _classify_pose(roll, pitch)
                imu_ok = (roll is not None and pitch is not None and yaw is not None)

                upd = {"ts": time.time(), "imu_ok": bool(imu_ok)}
                if pose is not None: upd["pose"] = pose
                if batt_pct is not None: upd["battery"] = batt_pct
                if roll is not None:
                    if not (float(roll) == 0.0 and LAST_XGO.get("roll") not in (None, 0.0)):
                        upd["roll"] = float(roll)
                if pitch is not None:
                    if not (float(pitch) == 0.0 and LAST_XGO.get("pitch") not in (None, 0.0)):
                        upd["pitch"] = float(pitch)
                if yaw is not None:
                    if not (float(yaw) == 0.0 and LAST_XGO.get("yaw") not in (None, 0.0)):
                        upd["yaw"] = float(yaw)

                LAST_XGO.update(upd)
                time.sleep(1.0)
            except Exception:
                time.sleep(1.0); cli = None
    except Exception as e:
        print(f"[api] xgo_ro_loop error: {e}", flush=True)

# --- Sysinfo + historia ---
_last_hist_t = 0.0
def get_sysinfo():
    global _last_hist_t
    ci = cpu_percent(); la1,la5,la15 = load_avg(); mi = mem_info(); di = disk_info("/"); tc = temp_c()
    now = time.time()
    if now - _last_hist_t >= 1.0:
        HIST_CPU.append(round(ci,1)); HIST_MEM.append(round(mi.get("pct",0.0),1))
        _last_hist_t = now
    si = {
        "ts": now,
        "cpu_pct": round(ci,1),
        "load": {"1": round(la1,2), "5": round(la5,2), "15": round(la15,2)},
        "mem": {"total": mi["total"], "available": mi["available"], "used": mi["used"], "pct": round(mi["pct"],1)},
        "disk": {"total": di["total"], "used": di["used"], "free": di["free"], "pct": round(di["pct"],1)},
        "temp_c": round(tc,1),
        "hist_cpu": list(HIST_CPU),
        "hist_mem": list(HIST_MEM),
        "os": _os_info(),
    }
    if LAST_XGO.get("battery") is not None:
        si["battery_pct"] = int(LAST_XGO["battery"])
    return si

# --- Middleware / headers ---
@app.after_request
def log_and_secure(resp):
    try: print(f"[api] {request.method} {request.path}", flush=True)
    except Exception: pass
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp

# === Handlers ================================================================
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

def state():
    now = time.time()
    ts = LAST_STATE.get("ts")
    age = (now - ts) if ts else None
    raw_ts = None
    try:
        st = os.stat(RAW_PATH); raw_ts = float(st.st_mtime)
    except Exception:
        pass
    fresh = (raw_ts is not None and (now - float(raw_ts)) <= LAST_FRESH_S)
    vision_enabled = bool(VISION_ENABLED or fresh)
    cache_bust = int(raw_ts or now)

    inferred_pose = LAST_XGO.get("pose") or _classify_pose(LAST_XGO.get("roll"), LAST_XGO.get("pitch"))

    resp = {
        "present": bool(LAST_STATE.get("present", False)),
        "confidence": float(LAST_STATE.get("confidence", 0.0)),
        "mode": LAST_STATE.get("mode"),
        "ts": ts,
        "age_s": round(age, 3) if age is not None else None,
        "camera": {"vision_enabled": vision_enabled, "has_last_frame": bool(raw_ts),
                   "last_frame_ts": int(raw_ts) if raw_ts else None,
                   "preview_url": f"/camera/last?t={cache_bust}",
                   "placeholder_url": "/camera/placeholder"},
        "devices": {
            "xgo": ({
                "present": True,
                "imu_ok": LAST_XGO.get("imu_ok"),
                "pose": inferred_pose,
                "battery_pct": LAST_XGO.get("battery"),
                "roll": LAST_XGO.get("roll"),
                "pitch": LAST_XGO.get("pitch"),
                "yaw": LAST_XGO.get("yaw"),
                "fw": XGO_FW,
                "ts": LAST_XGO.get("ts"),
            } if LAST_XGO.get("ts") else None)
        }
    }
    return Response(json.dumps(resp), mimetype="application/json")

def sysinfo():
    si = get_sysinfo()
    out = {
        "cpu_pct": si["cpu_pct"],
        "load1": si["load"]["1"], "load5": si["load"]["5"], "load15": si["load"]["15"],
        "mem_total_mb": round(si["mem"]["total"]/1048576,1),
        "mem_used_mb": round(si["mem"]["used"]/1048576,1),
        "mem_pct": si["mem"]["pct"],
        "disk_total_gb": round(si["disk"]["total"]/1073741824,1),
        "disk_used_gb": round(si["disk"]["used"]/1073741824,1),
        "disk_pct": si["disk"]["pct"],
        "temp_c": si["temp_c"],
        "hist_cpu": si["hist_cpu"],
        "hist_mem": si["hist_mem"],
        "os_release": ((si["os"].get("pretty") or "—")+" · "+(si["os"].get("kernel") or "—")),
        "ts": si["ts"],
    }
    if "battery_pct" in si and si["battery_pct"] is not None:
        out["battery_pct"] = si["battery_pct"]
    return Response(json.dumps(out), mimetype="application/json")

def metrics():
    si = get_sysinfo()
    now = time.time()
    last_msg_age = (now - LAST_MSG_TS) if LAST_MSG_TS else -1
    last_hb_age  = (now - LAST_HEARTBEAT_TS) if LAST_HEARTBEAT_TS else -1
    cam_age      = (now - LAST_CAMERA["ts"]) if LAST_CAMERA["ts"] else -1
    raw_age = -1
    if os.path.isfile(RAW_PATH):
        try: raw_age = max(0.0, now - float(os.stat(RAW_PATH).st_mtime))
        except Exception: raw_age = -1
    lines = []
    def m(name, val): lines.append(f"{name} {val}")
    m("rider_cpu_pct", si["cpu_pct"]); m("rider_mem_pct", si["mem"]["pct"]); m("rider_disk_pct", si["disk"]["pct"])
    m("rider_temp_c", si["temp_c"])
    if "battery_pct" in si and si["battery_pct"] is not None: m("rider_battery_pct", si["battery_pct"])
    m("rider_bus_last_msg_age_seconds", round(last_msg_age,3))
    m("rider_bus_last_heartbeat_age_seconds", round(last_hb_age,3))
    m("rider_camera_last_hb_age_seconds", round(cam_age,3))
    m("rider_camera_raw_age_seconds", round(raw_age,3))
    return Response("\n".join(lines) + "\n", mimetype="text/plain")

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

# --- Camera endpoints ---
def camera_raw():
    if not os.path.isfile(RAW_PATH):
        return Response(json.dumps({"error":"no_raw"}), mimetype="application/json", status=404)
    return send_from_directory(SNAP_DIR, "raw.jpg", cache_timeout=0)

def camera_proc():
    if not os.path.isfile(PROC_PATH):
        return Response(json.dumps({"error":"no_proc"}), mimetype="application/json", status=404)
    return send_from_directory(SNAP_DIR, "proc.jpg", cache_timeout=0)

def camera_last():
    if not os.path.isfile(RAW_PATH):
        return Response(json.dumps({"error":"no_raw"}), mimetype="application/json", status=404)
    resp = make_response(send_file(RAW_PATH, mimetype="image/jpeg"))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"; resp.headers["Expires"] = "0"
    return resp

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

# --- Snapshots (statyczne) ---
def snapshots_static(fname: str):
    safe = os.path.abspath(os.path.join(SNAP_DIR, fname))
    if not safe.startswith(SNAP_DIR): return abort(403)
    if not os.path.isfile(safe): return abort(404)
    return send_from_directory(SNAP_DIR, fname, cache_timeout=0)

# --- Services (whitelist) ---
def _unit_for(name: str) -> Optional[str]:
    if name in ALLOWED_UNITS: return ALLOWED_UNITS[name]
    if name in ALLOWED_UNITS.values(): return name
    return None

def _svc_status(unit: str) -> dict:
    try:
        out = subprocess.check_output(
            ["systemctl","show",unit,"--no-page","--property=ActiveState,SubState,UnitFileState,LoadState,Description"],
            stderr=subprocess.STDOUT, text=True, timeout=2.0
        )
        kv = {}
        for line in out.splitlines():
            if "=" in line:
                k,v = line.split("=",1)
                kv[k.strip()] = v.strip()
        return {"unit": unit, "load": kv.get("LoadState"), "active": kv.get("ActiveState"),
                "sub": kv.get("SubState"), "enabled": kv.get("UnitFileState"), "desc": kv.get("Description")}
    except Exception as e:
        return {"unit": unit, "error": str(e)}

def svc_list():
    return Response(json.dumps({"services":[_svc_status(u) for u in sorted(set(ALLOWED_UNITS.values()))]}),
                    mimetype="application/json")

def svc_status(name: str):
    unit = _unit_for(name)
    if not unit:
        return Response(json.dumps({"error":"unknown service"}), mimetype="application/json", status=404)
    return Response(json.dumps(_svc_status(unit)), mimetype="application/json")

def svc_action(name: str):
    unit = _unit_for(name)
    if not unit:
        return Response(json.dumps({"error":"unknown service"}), mimetype="application/json", status=404)
    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").lower()
    if action not in ("start","stop","restart","enable","disable"):
        return Response(json.dumps({"error":"bad action"}), mimetype="application/json", status=400)
    if not os.path.isfile(SERVICE_CTL) or not os.access(SERVICE_CTL, os.X_OK):
        return Response(json.dumps({"error":"service_ctl_missing",
                                    "hint":"chmod +x ops/service_ctl.sh & add sudoers NOPASSWD"}),
                        mimetype="application/json", status=501)
    try:
        proc = subprocess.run(["sudo","-n",SERVICE_CTL,unit,action], check=False, capture_output=True, text=True, timeout=8.0)
        status = _svc_status(unit)
        return Response(json.dumps({"ok": (proc.returncode==0), "rc": proc.returncode,
                                    "stdout": (proc.stdout or "")[-4000:], "stderr": (proc.stderr or "")[-4000:],
                                    "status": status}),
                        mimetype="application/json", status=(200 if proc.returncode==0 else 500))
    except subprocess.TimeoutExpired:
        return Response(json.dumps({"error":"timeout"}), mimetype="application/json", status=504)
    except Exception as e:
        return Response(json.dumps({"error": str(e)}), mimetype="application/json", status=500)

# --- Dashboard/Control -------------------------------------------------------
def dashboard():
    if not os.path.isfile(VIEW_HTML):
        return Response(
            "<h1>Rider-Pi API</h1><p>Brak web/view.html – użyj <a href='/state'>/state</a>, "
            "<a href='/sysinfo'>/sysinfo</a>, <a href='/healthz'>/healthz</a>.</p>",
            mimetype="text/html"
        ), 200
    return send_file(VIEW_HTML)

def control_page():
    if not os.path.isfile(CONTROL_HTML):
        return Response("<h1>control.html missing</h1>", mimetype="text/html"), 404
    return send_file(CONTROL_HTML)

# --- API sterowania (wysyłka przez PUB) -------------------------------------
def api_move():
    data = request.get_json(silent=True) or {}
    vx  = float(data.get("vx", 0.0)); vy = float(data.get("vy", 0.0)); yaw = float(data.get("yaw", 0.0))
    duration = float(data.get("duration", 0.0))
    bus_pub("cmd.move", {"vx": vx, "vy": vy, "yaw": yaw, "duration": duration, "ts": time.time()})
    return Response(json.dumps({"ok": True}), mimetype="application/json")

def api_stop():
    bus_pub("cmd.stop", {"ts": time.time()})
    return Response(json.dumps({"ok": True}), mimetype="application/json")

def api_preset():
    name = (request.get_json(silent=True) or {}).get("name")
    bus_pub("cmd.preset", {"name": name, "ts": time.time()})
    return Response(json.dumps({"ok": True}), mimetype="application/json")

def api_voice():
    text = (request.get_json(silent=True) or {}).get("text", "")
    bus_pub("cmd.voice", {"text": text, "ts": time.time()})
    return Response(json.dumps({"ok": True}), mimetype="application/json")

def api_cmd():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return Response(json.dumps({"error":"JSON object expected"}), mimetype="application/json", status=400)
    t = (data.get("type") or "").lower(); ts = time.time()
    try:
        if t == "drive":
            vx  = float(data.get("lx") or data.get("vx") or 0.0)
            yaw = float(data.get("az") or data.get("yaw") or 0.0)
            dur = float(data.get("dur") or data.get("duration") or 0.0)
            bus_pub("cmd.move", {"vx": vx, "yaw": yaw, "duration": dur, "ts": ts}); return Response(json.dumps({"ok": True}), mimetype="application/json")
        if t == "stop":
            bus_pub("cmd.stop", {"ts": ts}); return Response(json.dumps({"ok": True}), mimetype="application/json")
        if t == "spin":
            dir_ = (data.get("dir") or "").lower()
            speed = float(data.get("speed") or 0.3); dur = float(data.get("dur") or data.get("duration") or 0.45)
            yaw   = -abs(speed) if dir_ == "left" else +abs(speed)
            bus_pub("cmd.move", {"vx": 0.0, "yaw": yaw, "duration": dur, "ts": ts}); return Response(json.dumps({"ok": True}), mimetype="application/json")
        bus_pub("cmd.raw", {"payload": data, "ts": ts})
        return Response(json.dumps({"ok": True, "note": "unknown type -> cmd.raw"}), mimetype="application/json")
    except Exception as e:
        return Response(json.dumps({"error": str(e)}), mimetype="application/json", status=500)

def api_pub_generic():
    data = request.get_json(silent=True) or {}
    topic = data.get("topic"); message = data.get("message")
    if not topic or message is None:
        return Response(json.dumps({"error":"need {topic, message}"}), mimetype="application/json", status=400)
    if not isinstance(message, str): message = json.dumps(message, ensure_ascii=False)
    if _ZMQ_OK and _ZMQ_PUB is not None:
        _ZMQ_PUB.send_string(f"{topic} {message}")
        return Response(json.dumps({"ok": True}), mimetype="application/json")
    return Response(json.dumps({"error":"bus not available"}), mimetype="application/json", status=503)

# --- Routing -----------------------------------------------------------------
def register_routes(flask_app: Flask):
    add: Callable[..., None] = flask_app.add_url_rule

    # proste
    add("/healthz", view_func=healthz, methods=["GET"])
    add("/health",  view_func=health_alias, methods=["GET"])
    add("/state",   view_func=state, methods=["GET"])
    add("/sysinfo", view_func=sysinfo, methods=["GET"])
    add("/metrics", view_func=metrics, methods=["GET"])
    add("/events",  view_func=events, methods=["GET"])

    # camera
    add("/camera/raw",         view_func=camera_raw, methods=["GET","HEAD"])
    add("/camera/proc",        view_func=camera_proc, methods=["GET","HEAD"])
    add("/camera/last",        view_func=camera_last, methods=["GET","HEAD"])
    add("/camera/placeholder", view_func=camera_placeholder, methods=["GET","HEAD"])

    # services
    add("/svc",                view_func=svc_list, methods=["GET"])
    add("/svc/<string:name>/status", view_func=svc_status, methods=["GET"])
    add("/svc/<string:name>",        view_func=svc_action, methods=["POST"])

    # dashboard
    add("/",          view_func=dashboard, methods=["GET"])
    add("/control",   view_func=control_page, methods=["GET"])

    # cmd/api
    add("/api/move",  view_func=api_move, methods=["POST"])
    add("/api/stop",  view_func=api_stop, methods=["POST"])
    add("/api/preset",view_func=api_preset, methods=["POST"])
    add("/api/voice", view_func=api_voice, methods=["POST"])
    add("/api/cmd",   view_func=api_cmd, methods=["POST"])

    # pub + snapshots
    add("/pub", view_func=api_pub_generic, methods=["POST"])
    add("/snapshots/<path:fname>", view_func=snapshots_static, methods=["GET"])

# --- Start / startery wątków -------------------------------------------------
START_TS = time.time()

def start_bus_sub():
    """Uruchom subskrypcję BUS (idempotentnie)."""
    if not _ZMQ_OK:
        print("[api] bus_sub_loop unavailable or pyzmq missing — skipping", flush=True)
        return
    if getattr(start_bus_sub, "_started", False):
        return
    t = threading.Thread(target=bus_sub_loop, daemon=True)
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
    try:
        t = threading.Thread(target=xgo_ro_loop, daemon=True)
        t.start()
        start_xgo_ro._started = True
        print("[api] xgo_ro_loop started", flush=True)
    except Exception as e:
        print("[api] xgo_ro_loop unavailable — skipping", e, flush=True)

# Rejestracja tras NATYCHMIAST (pod import)
register_routes(app)

if __name__ == "__main__":
    try: os.makedirs(SNAP_DIR, exist_ok=True)
    except Exception: pass
    print(f"[api] starting on 0.0.0.0:{STATUS_API_PORT} (bus sub:{BUS_SUB_PORT})", flush=True)
    start_bus_sub()
    start_xgo_ro()
    app.run(host="0.0.0.0", port=STATUS_API_PORT, threaded=True)
