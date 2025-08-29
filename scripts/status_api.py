#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rider-Pi – Status API + mini dashboard (Flask 1.x compatible)

Endpoints:
- /            : dashboard (HTML/JS)
- /healthz     : status + bus ages + devices (camera/lcd/xgo)
- /state       : last vision.state
- /sysinfo     : CPU/MEM/LOAD/DISK/TEMP (+ history for dashboard) + OS info
- /metrics     : Prometheus-style, very small set
- /events      : SSE live bus events (vision.*, camera.*)

Zależności: flask, (opcjonalnie) pyzmq; API działa nawet bez ZMQ/XGO.
Testowane na Python 3.9 (RPi OS).
"""

import os, time, json, threading, collections, shutil, subprocess, platform
from datetime import datetime
from flask import Flask, Response, stream_with_context, request

# --- Konfiguracja ---
BUS_PUB_PORT = int(os.getenv("BUS_PUB_PORT", "5555"))
BUS_SUB_PORT = int(os.getenv("BUS_SUB_PORT", "5556"))
STATUS_API_PORT = int(os.getenv("STATUS_API_PORT", "8080"))

ENV_DISABLE_LCD = (os.getenv("DISABLE_LCD", "0") == "1")
ENV_NO_DRAW     = (os.getenv("NO_DRAW", "0") == "1")
ENV_ROT         = int(os.getenv("PREVIEW_ROT", "0") or 0)

REFRESH_S   = 2.0
HISTORY_LEN = 60  # ~60 punktów, ~1 pkt / sekundę

app = Flask(__name__)

# --- Stan wewnętrzny ---
LAST_MSG_TS = None
LAST_HEARTBEAT_TS = None
LAST_STATE = {"present": False, "confidence": 0.0, "ts": None}

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
    "ts": None,          # timestamp ostatniego odczytu
    "imu_ok": False,
    "pose": None,
    "battery": None,     # %
    "roll": None,
    "pitch": None,
    "yaw": None,
}
XGO_FW = None            # wersja firmware odczytana raz

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

# --- Narzędzia sysinfo (bez psutil) ---
def _cpu_pct_sample():
    """Bardzo uproszczone %CPU: korzystamy z /proc/stat pomiarem różnicowym."""
    try:
        with open("/proc/stat", "r") as f:
            line = f.readline()
        if not line.startswith("cpu "):  # spacja!
            return 0.0
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
    # najpierw /sys, potem vcgencmd
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            t = float(f.read().strip()) / 1000.0
            return t
    except Exception:
        pass
    try:
        out = subprocess.check_output(["vcgencmd", "measure_temp"]).decode()
        # temp=55.0'C
        v = out.strip().split("=")[-1].replace("'C", "").replace("C", "").replace("'", "")
        return float(v)
    except Exception:
        return 0.0

def _os_info():
    """PrettyName + kernel."""
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
        # interesują nas vision.* i camera.*
        sub.setsockopt_string(zmq.SUBSCRIBE, "vision.")
        sub.setsockopt_string(zmq.SUBSCRIBE, "camera.")
        print(f"[api] SUB connected tcp://127.0.0.1:{BUS_SUB_PORT}", flush=True)

        while True:
            try:
                msg = sub.recv_string()
                LAST_MSG_TS = time.time()
                topic, payload = msg.split(" ", 1)
                EVENTS.append({"ts": LAST_MSG_TS, "topic": topic, "data": payload})
                if topic == "vision.dispatcher.heartbeat":
                    LAST_HEARTBEAT_TS = LAST_MSG_TS
                elif topic == "vision.state":
                    try:
                        data = json.loads(payload)
                        LAST_STATE = {
                            "present": bool(data.get("present", False)),
                            "confidence": float(data.get("confidence", 0.0)),
                            "ts": data.get("ts"),
                        }
                    except Exception:
                        pass
                elif topic == "camera.heartbeat":
                    try:
                        data = json.loads(payload)
                        LAST_CAMERA["ts"] = LAST_MSG_TS
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
    """
    Lekki „RO” klient, odczytuje: battery/roll/pitch/yaw, liczy pose.
    Nie wykonuje żadnych komend ruchu.
    """
    global LAST_XGO, XGO_FW
    try:
        # opóźnienie startu, by system się unormował
        time.sleep(0.5)
        # import dopiero w wątku (brak twardej zależności przy starcie)
        try:
            from scripts.xgo_client_ro import XGOClientRO  # type: ignore
        except Exception as e:
            print("[api] xgo_ro_loop import error:", e, flush=True)
            return

        cli = None
        while True:
            try:
                if cli is None:
                    cli = XGOClientRO(port="/dev/ttyAMA0")
                    print("[api] XGO RO connected: /dev/ttyAMA0", flush=True)

                # fw zapamiętujemy jednokrotnie
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
                # spróbuj zrekonektować za chwilę
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
    if now - _last_hist_t >= 1.0:  # próbkuj ~1 Hz do wykresu
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
    # fallback bateria (z XGO)
    if LAST_XGO.get("battery") is not None:
        si["battery_pct"] = int(LAST_XGO["battery"])
    return si

# --- Endpoints JSON ---
@app.after_request
def log_and_secure(resp):
    # krótki log (metoda + path)
    try:
        print(f"[api] {request.method} {request.path}", flush=True)
    except Exception:
        pass
    # bezpieczne nagłówki (nie dotykamy cache-control dla JSON)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp

@app.route("/healthz")
def healthz():
    now = time.time()
    last_msg_age = (now - LAST_MSG_TS) if LAST_MSG_TS else None
    last_hb_age  = (now - LAST_HEARTBEAT_TS) if LAST_HEARTBEAT_TS else None

    # devices
    cam_age = (now - LAST_CAMERA["ts"]) if LAST_CAMERA["ts"] else None
    camera_on = (cam_age is not None and cam_age <= 5.0)

    # xgo
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
        "ts": ts,
        "age_s": round(age, 3) if age is not None else None,
    }
    return Response(json.dumps(payload), mimetype="application/json")

@app.route("/sysinfo")
def sysinfo():
    return Response(json.dumps(get_sysinfo()), mimetype="application/json")

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

# --- Dashboard HTML ---
DASHBOARD_HTML = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Rider-Pi — mini dashboard</title>
<style>
 body{margin:0;background:#0e1a24;color:#d7e2ee;font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
 .wrap{max-width:980px;margin:28px auto;padding:0 18px}
 h1{font-size:28px;margin:0 0 8px}
 .hint{opacity:.6;font-size:12px;margin-bottom:18px}
 .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}
 .card{background:#0f2233;border:1px solid #1d3548;border-radius:12px;padding:14px;box-shadow:0 2px 10px rgba(0,0,0,.25)}
 .card h3{margin:0 0 10px;font-size:16px;color:#9cc8ff}
 .kv{display:grid;grid-template-columns:1fr auto;gap:6px 10px;font-size:13px}
 .kv div{opacity:.9}
 .ok{color:#5fe39a} .bad{color:#ff6b6b} .muted{opacity:.6}
 canvas{width:100%;height:140px;background:#0c1b28;border-radius:8px;border:1px solid #1d3548}
 a{color:#87b7ff}
 .legend{display:flex;gap:14px;margin-top:6px; font-size:12px; opacity:.8}
 .dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:middle}
 .cpu{background:#6db3ff}.mem{background:#ffd36d}
</style>
</head>
<body>
<div class="wrap">
  <h1>Rider-Pi — mini dashboard</h1>
  <div class="hint">Auto-refresh co ≈ 2 s. Endpointy: <a href="/healthz">/healthz</a>, <a href="/state">/state</a>, <a href="/sysinfo">/sysinfo</a></div>

  <div class="grid">
    <!-- System -->
    <div class="card">
      <h3>System</h3>
      <div class="kv">
        <div>cpu</div><div id="ci_cpu" class="muted">—</div>
        <div>load (1/5/15)</div><div id="ci_load" class="muted">—</div>
        <div>mem</div><div id="ci_mem" class="muted">—</div>
        <div>disk</div><div id="ci_disk" class="muted">—</div>
        <div>os</div><div id="ci_os" class="muted">—</div>
        <div>fw</div><div id="ci_fw" class="muted">—</div>
      </div>
    </div>

    <!-- Devices -->
    <div class="card">
      <h3>Devices</h3>
      <div class="kv">
        <div>camera</div><div id="d_cam" class="muted">—</div>
        <div>lcd</div><div id="d_lcd" class="muted">—</div>
        <div>xgo.imu</div><div id="d_xgo_imu" class="muted">—</div>
        <div>xgo.pose</div><div id="d_xgo_pose" class="muted">—</div>
        <div>xgo.battery</div><div id="d_xgo_batt" class="muted">—</div>
        <div>temp</div><div id="d_temp" class="muted">—</div>
      </div>
    </div>

    <!-- History -->
    <div class="card">
      <h3>History (60 s) — CPU / MEM</h3>
      <canvas id="chart" width="300" height="140"></canvas>
      <div class="legend">
        <span><i class="dot cpu"></i>cpu%</span>
        <span><i class="dot mem"></i>mem%</span>
      </div>
    </div>
  </div>

  <div class="grid" style="margin-top:18px">
    <!-- Health -->
    <div class="card">
      <h3>Health</h3>
      <div class="kv">
        <div>status</div><div id="h_status" class="ok">ok</div>
        <div>uptime</div><div id="h_uptime" class="muted">—</div>
        <div>bus.last_msg_age</div><div id="h_msg" class="muted">—</div>
        <div>bus.last_heartbeat_age</div><div id="h_hb" class="muted">—</div>
      </div>
    </div>

    <!-- Presence -->
    <div class="card">
      <h3>Presence (vision.state)</h3>
      <div class="kv">
        <div>present</div><div id="p_present" class="bad">false</div>
        <div>confidence</div><div id="p_conf" class="muted">0.000</div>
        <div>ts</div><div id="p_ts" class="muted">—</div>
        <div>age</div><div id="p_age" class="muted">—</div>
      </div>
    </div>

    <!-- Links -->
    <div class="card">
      <h3>Links</h3>
      <div class="kv">
        <div>events (SSE)</div><div><a href="/events" target="_blank">/events</a></div>
        <div>metrics</div><div><a href="/metrics" target="_blank">/metrics</a></div>
        <div>repo</div><div><a href="https://github.com/pppnews/Rider-Pi" target="_blank">Rider-Pi</a></div>
      </div>
    </div>
  </div>

  <div class="hint" style="margin-top:14px">
    © Rider-Pi – <a href="/healthz">/healthz</a> · <a href="/state">/state</a> · <a href="/sysinfo">/sysinfo</a>
  </div>
</div>

<script>
const REFRESH = 2000;
const fmt = (n, d=1)=> (n==null? '—' : (typeof n==='number'? Number(n).toFixed(d): n));
const el = id => document.getElementById(id);
const setTxt=(id,txt)=>{const e=el(id); if(e) e.textContent=txt;}
const setCls=(id,cls)=>{const e=el(id); if(e) e.className=cls;}

function drawChart(cpuArr, memArr){
  const c = el('chart'); if(!c) return;
  const ctx = c.getContext('2d');
  ctx.clearRect(0,0,c.width,c.height);
  const pad=10, W=c.width-pad*2, H=c.height-pad*2;
  ctx.strokeStyle='#1d3548'; ctx.strokeRect(pad,pad,W,H);
  function plot(arr, color){
    if(!arr || arr.length<2) return;
    const n = arr.length, max=100, min=0;
    ctx.beginPath(); ctx.lineWidth=1.2; ctx.strokeStyle=color;
    for(let i=0;i<n;i++){
      const x = pad + (i*(W/(n-1)));
      const v = Math.max(min, Math.min(max, Number(arr[i]||0)));
      const y = pad + H - ((v-min)/(max-min))*H;
      if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
    }
    ctx.stroke();
  }
  plot(cpuArr,'#6db3ff'); // cpu
  plot(memArr,'#ffd36d'); // mem
}

function updateHealth(h){
  setTxt('h_status', h.status || '—');
  setCls('h_status', (h.status==='ok')? 'ok':'bad');
  // uptime jako HH:MM:SS
  if(h.uptime_s!=null){
    const s = Math.floor(h.uptime_s);
    const HH = Math.floor(s/3600);
    const MM = String(Math.floor((s%3600)/60)).padStart(2,'0');
    const SS = String(s%60).padStart(2,'0');
    setTxt('h_uptime', `${HH}:${MM}:${SS}`);
  } else setTxt('h_uptime','—');

  setTxt('h_msg', (h.bus && h.bus.last_msg_age_s!=null)? fmt(h.bus.last_msg_age_s,1)+' s':'—');
  setTxt('h_hb',  (h.bus && h.bus.last_heartbeat_age_s!=null)? fmt(h.bus.last_heartbeat_age_s,1)+' s':'—');

  if(h.devices){
    const cam = h.devices.camera || {};
    const camTxt = (cam.on? 'ON':'OFF')
      + (cam.mode? (' · '+cam.mode):'')
      + (cam.fps!=null? (' · '+fmt(cam.fps,1)+' fps'):'')
      + (cam.age_s!=null? (' · '+fmt(cam.age_s,1)+'s'):'');
    setTxt('d_cam', camTxt); setCls('d_cam', cam.on? 'ok':'muted');

    const lcd = h.devices.lcd || {};
    const lcdTxt = (lcd.on? 'ON':'OFF')
      + (lcd.rot!=null? (' · rot '+lcd.rot):'')
      + (lcd.no_draw? ' · no_draw':'' );
    setTxt('d_lcd', lcdTxt); setCls('d_lcd', lcd.on? 'ok':'muted');

    const xgo = h.devices.xgo || {};
    const imuTxt = (xgo.on? 'ON':'OFF')
      + (xgo.imu_ok===true? ' · OK': (xgo.on? ' · ?':''))
      + (xgo.age_s!=null? (' · '+fmt(xgo.age_s,1)+'s'):'');
    setTxt('d_xgo_imu', imuTxt);
    setCls('d_xgo_imu', (xgo.on && xgo.imu_ok)? 'ok' : (xgo.on? 'muted':'muted'));

    const poseTxt = (xgo.pose!=null? String(xgo.pose):'—')
      + (xgo.roll!=null? (` · r ${fmt(xgo.roll,1)}°`):'')
      + (xgo.pitch!=null? (` · p ${fmt(xgo.pitch,1)}°`):'')
      + (xgo.yaw!=null? (` · y ${fmt(xgo.yaw,1)}°`):'');
    setTxt('d_xgo_pose', poseTxt);
    setCls('d_xgo_pose', (xgo.pose==='upright')? 'ok' : (xgo.pose ? 'bad' : 'muted'));

    const battTxt = (xgo.battery_pct!=null? `${xgo.battery_pct}%`:'—');
    setTxt('d_xgo_batt', battTxt);
    setCls('d_xgo_batt', (xgo.battery_pct!=null? 'ok':'muted'));

    // pokaż fw na karcie System (jeśli jest)
    if (xgo.fw) setTxt('ci_fw', xgo.fw);
  }
}

function updateState(s){
  setTxt('p_present', String(!!s.present));
  setCls('p_present', s.present? 'ok':'bad');
  setTxt('p_conf', fmt(s.confidence,3));
  setTxt('p_ts', s.ts? new Date(s.ts*1000).toLocaleTimeString(): '—');
  setTxt('p_age', (s.age_s!=null? fmt(s.age_s,1)+' s':'—'));
}

function updateSys(si){
  setTxt('ci_cpu',  fmt(si?.cpu_pct,1)+'%');
  setTxt('ci_load', fmt(si?.load?.['1'],2)+'/'+fmt(si?.load?.['5'],2)+'/'+fmt(si?.load?.['15'],2));
  const mb = v=> (v/1048576).toFixed(1)+' MB';
  const gb = v=> (v/1073741824).toFixed(1)+' GB';
  if (si?.mem)  setTxt('ci_mem',  mb(si.mem.used)+' / '+mb(si.mem.total)+' ('+fmt(si.mem.pct,1)+'%)');
  if (si?.disk) setTxt('ci_disk', gb(si.disk.used)+' / '+gb(si.disk.total)+' ('+fmt(si.disk.pct,1)+'%)');

  const osPretty = si?.os?.pretty || '—';
  const osKernel = si?.os?.kernel || '—';
  setTxt('ci_os', `${osPretty} · ${osKernel}`);

  // temp w Devices
  setTxt('d_temp', (si?.temp_c!=null? fmt(si.temp_c,1)+' °C' : '—'));

  drawChart(si?.hist_cpu||[], si?.hist_mem||[]);
}

async function tick(){
  try{ const h  = await (await fetch('/healthz',{cache:'no-store'})).json(); updateHealth(h);}catch(e){}
  try{ const s  = await (await fetch('/state',{cache:'no-store'})).json();   updateState(s);}catch(e){}
  try{ const si = await (await fetch('/sysinfo',{cache:'no-store'})).json(); updateSys(si);}catch(e){}
}

setInterval(tick, REFRESH);
window.addEventListener('load', tick);
</script>
</body>
</html>
"""

@app.route("/")
def dashboard():
    return Response(DASHBOARD_HTML, mimetype="text/html", headers={"Cache-Control":"no-store"})

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
    start_bus_sub()
    start_xgo_ro()
    app.run(host="0.0.0.0", port=STATUS_API_PORT, threaded=True)

