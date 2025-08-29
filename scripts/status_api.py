# scripts/status_api.py
# Rider-Pi — lekki Status API (Flask 1.x) + mini-dashboard + SSE + /metrics + /sysinfo
import os, time, json, threading, shutil
from collections import deque
from flask import Flask, jsonify, Response, request, stream_with_context

APP_START = time.time()
BUS_PUB_PORT = int(os.getenv("BUS_PUB_PORT", "5555"))
BUS_SUB_PORT = int(os.getenv("BUS_SUB_PORT", "5556"))
STATUS_API_PORT = int(os.getenv("STATUS_API_PORT", "8080"))

# --- ZMQ (opcjonalne) ---
try:
    import zmq  # type: ignore
    _HAS_ZMQ = True
except Exception:
    _HAS_ZMQ = False

app = Flask(__name__)

# --- Bufory i stan ---
events_buf = deque(maxlen=500)           # dla SSE /events
last_msg_ts = None                       # timestamp ostatniej wiadomości z busa
last_hb_ts = None                        # heartbeat z dispatchera
state_cache = {"present": False, "confidence": 0.0, "ts": None}

# --- Prosty system monitor (/sysinfo) ---
_sysinfo_cache = {}
def _read_cpu_jiffies():
    try:
        with open("/proc/stat","r") as f:
            parts = f.readline().split()
        if parts[0] != "cpu": return None
        vals = list(map(int, parts[1:8]))  # user nice system idle iowait irq softirq
        idle = vals[3] + vals[4]
        nonidle = vals[0] + vals[1] + vals[2] + vals[5] + vals[6]
        total = idle + nonidle
        return total, idle
    except Exception:
        return None

def _sysmon_loop():
    prev = _read_cpu_jiffies()
    while True:
        try:
            time.sleep(1.0)
            now = time.time()
            cur = _read_cpu_jiffies()
            if prev and cur:
                totald = cur[0] - prev[0]
                idled  = cur[1] - prev[1]
                cpu_pct = max(0.0, min(100.0, (1 - (idled/totald)) * 100.0)) if totald>0 else 0.0
            else:
                cpu_pct = 0.0
            prev = cur

            try:
                load1, load5, load15 = os.getloadavg()
            except Exception:
                load1=load5=load15=None

            # memory
            mem_total_mb=mem_used_mb=mem_pct=None
            try:
                mem_total_k = mem_avail_k = None
                with open("/proc/meminfo","r") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):     mem_total_k  = int(line.split()[1])
                        elif line.startswith("MemAvailable:"): mem_avail_k = int(line.split()[1])
                if mem_total_k and mem_avail_k is not None:
                    used_k = mem_total_k - mem_avail_k
                    mem_total_mb = round(mem_total_k/1024.0,1)
                    mem_used_mb  = round(used_k/1024.0,1)
                    mem_pct      = round((mem_used_mb/mem_total_mb)*100.0,1)
            except Exception:
                pass

            # disk
            disk_total_gb=disk_used_gb=disk_pct=None
            try:
                du = shutil.disk_usage("/")
                disk_total_gb = round(du.total/1024/1024/1024,2)
                disk_used_gb  = round((du.total-du.free)/1024/1024/1024,2)
                disk_pct      = round((disk_used_gb/disk_total_gb)*100.0,1)
            except Exception:
                pass

            # temp
            temp_c = None
            for path in ("/sys/class/thermal/thermal_zone0/temp",
                         "/sys/devices/virtual/thermal/thermal_zone0/temp"):
                try:
                    with open(path,"r") as f:
                        v = f.read().strip()
                        temp_c = (int(v)/1000.0) if v.isdigit() else float(v)
                    break
                except Exception:
                    pass

            _sysinfo_cache.update({
                "ts": now,
                "cpu_pct": round(cpu_pct,1),
                "load1": load1 if load1 is None else round(load1,2),
                "load5": load5 if load5 is None else round(load5,2),
                "load15": load15 if load15 is None else round(load15,2),
                "mem_total_mb": mem_total_mb,
                "mem_used_mb": mem_used_mb,
                "mem_pct": mem_pct,
                "disk_total_gb": disk_total_gb,
                "disk_used_gb": disk_used_gb,
                "disk_pct": disk_pct,
                "temp_c": None if temp_c is None else round(temp_c,1),
            })
        except Exception:
            time.sleep(1.0)

def start_sysmon():
    threading.Thread(target=_sysmon_loop, daemon=True).start()

# --- Wątek subskrypcji busa (jeśli mamy ZMQ) ---
def start_bus_sub():
    if not _HAS_ZMQ:
        print("[api] pyzmq not available; running without bus subscribe")
        return
    def loop():
        global last_msg_ts, last_hb_ts, state_cache
        try:
            ctx = zmq.Context.instance()
            sub = ctx.socket(zmq.SUB)
            sub.connect(f"tcp://127.0.0.1:{BUS_SUB_PORT}")
            for t in ("vision.state", "vision.dispatcher.heartbeat"):
                sub.setsockopt_string(zmq.SUBSCRIBE, t)
            print(f"[api] SUB connected tcp://127.0.0.1:{BUS_SUB_PORT}")
            while True:
                topic, payload = sub.recv_string().split(" ", 1)
                last_msg_ts = time.time()
                try:
                    data = json.loads(payload)
                except Exception:
                    data = {"raw": payload}
                events_buf.append({"ts": last_msg_ts, "topic": topic, "data": data})
                if topic == "vision.dispatcher.heartbeat":
                    last_hb_ts = last_msg_ts
                elif topic == "vision.state":
                    state_cache = {
                        "present": bool(data.get("present", False)),
                        "confidence": float(data.get("confidence", 0.0)),
                        "ts": float(data.get("ts", last_msg_ts))
                    }
        except Exception as e:
            print("[api] bus loop error:", e)
            time.sleep(1.0)
    threading.Thread(target=loop, daemon=True).start()

# --- Routes ---
@app.route("/healthz")
def healthz():
    now = time.time()
    bus_msg_age = None if last_msg_ts is None else round(now - last_msg_ts, 3)
    hb_age      = None if last_hb_ts  is None else round(now - last_hb_ts, 3)
    status = "ok" if (hb_age is not None and hb_age < 10.0) else "degraded"
    return jsonify({
        "status": status,
        "uptime_s": round(now - APP_START, 3),
        "bus": {
            "last_msg_age_s": bus_msg_age,
            "last_heartbeat_age_s": hb_age,
        }
    })

@app.route("/state")
def state():
    now = time.time()
    ts = state_cache.get("ts")
    age = None if ts is None else round(now - ts, 3)
    return jsonify({
        "present": bool(state_cache.get("present", False)),
        "confidence": float(state_cache.get("confidence", 0.0)),
        "ts": ts, "age_s": age
    })

@app.route("/sysinfo")
def sysinfo():
    d = dict(_sysinfo_cache)
    if d.get("ts") is not None:
        d["age_s"] = round(time.time() - d["ts"], 3)
    else:
        d["age_s"] = None
    return jsonify(d)

@app.route("/metrics")
def metrics():
    now = time.time()
    hb_age = "NaN" if last_hb_ts is None else f"{now - last_hb_ts:.3f}"
    msg_age= "NaN" if last_msg_ts is None else f"{now - last_msg_ts:.3f}"
    present = 1 if state_cache.get("present") else 0
    conf = float(state_cache.get("confidence", 0.0))
    lines = []
    lines.append(f'rider_status_uptime_seconds {now-APP_START:.3f}')
    lines.append(f'rider_bus_last_heartbeat_age_seconds {hb_age}')
    lines.append(f'rider_bus_last_msg_age_seconds {msg_age}')
    lines.append(f'rider_vision_present {present}')
    lines.append(f'rider_vision_confidence {conf:.3f}')
    # sysinfo (jeśli mamy)
    si = _sysinfo_cache
    def m(name, val):
        if val is None: return
        lines.append(f'{name} {val}')
    m("rider_sys_cpu_pct", si.get("cpu_pct"))
    m("rider_sys_mem_pct", si.get("mem_pct"))
    m("rider_sys_disk_pct", si.get("disk_pct"))
    if si.get("temp_c") is not None:
        lines.append(f'rider_sys_temp_c {si["temp_c"]}')
    return Response("\n".join(lines) + "\n", mimetype="text/plain; version=0.0.4")

@app.route("/events")
def sse_events():
    @stream_with_context
    def gen():
        yield ": ok\n\n"
        while True:
            time.sleep(1.0)
            for ev in list(events_buf)[-10:]:
                payload = json.dumps(ev, ensure_ascii=False)
                yield f"data: {payload}\n\n"
    headers = {"Content-Type":"text/event-stream", "Cache-Control":"no-store"}
    return Response(gen(), headers=headers)

# --- Dashboard HTML (z wykresem CPU/MEM 60 s) ---
DASHBOARD_HTML = r"""
<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Rider-Pi — mini dashboard</title>
<style>
:root { --bg:#0f1a26; --card:#142233; --fg:#dbe6f7; --muted:#8aa0bd; --ok:#6bd36b; --bad:#ff6b6b; --warn:#f0c36b; }
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.4 system-ui,Segoe UI,Roboto,Arial}
.wrap{max-width:980px;margin:32px auto;padding:0 16px}
h1{margin:0 0 6px 0} .muted{color:var(--muted);font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px;margin-top:16px}
.card{background:var(--card);padding:16px;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,.25)}
h3{margin:0 0 8px 0;font-size:18px}
.row{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px dashed rgba(255,255,255,.08)}
.row:last-child{border-bottom:0}
.k{color:var(--muted)} .v{text-align:right}
.bad{color:var(--bad)} .ok{color:var(--ok)} .warn{color:var(--warn)}
.footer{margin-top:16px;color:var(--muted);font-size:12px}
.chart{position:relative}
canvas{width:100%;height:160px;display:block;background:#0c1722;border-radius:8px}
.legend{display:flex;gap:12px;margin-top:6px;font-size:12px;color:var(--muted)}
.legend i{width:10px;height:10px;border-radius:2px;display:inline-block;margin-right:6px}
.i-cpu{background:#f0c36b}.i-mem{background:#59a9ff}
</style>
</head><body>
<div class="wrap">
  <h1>Rider-Pi — mini dashboard</h1>
  <div class="muted">Auto-refresh co 2 s. Endpointy: /healthz, /state, /sysinfo</div>

  <div class="grid">

    <div class="card">
      <h3>Health</h3>
      <div class="row"><div class="k">status</div><div class="v" id="h_status">—</div></div>
      <div class="row"><div class="k">uptime</div><div class="v" id="h_uptime">—</div></div>
      <div class="row"><div class="k">bus.last_msg_age</div><div class="v" id="h_msg">—</div></div>
      <div class="row"><div class="k">bus.last_heartbeat_age</div><div class="v" id="h_hb">—</div></div>
    </div>

    <div class="card">
      <h3>Presence (vision.state)</h3>
      <div class="row"><div class="k">present</div><div class="v" id="s_present">—</div></div>
      <div class="row"><div class="k">confidence</div><div class="v" id="s_conf">—</div></div>
      <div class="row"><div class="k">ts</div><div class="v" id="s_ts">—</div></div>
      <div class="row"><div class="k">age</div><div class="v" id="s_age">—</div></div>
    </div>

    <div class="card">
      <h3>History (60 s) — CPU / MEM</h3>
      <div class="chart">
        <canvas id="hist" width="640" height="160"></canvas>
        <div class="legend">
          <span><i class="i-cpu"></i>cpu %</span>
          <span><i class="i-mem"></i>mem %</span>
        </div>
      </div>
    </div>

    <div class="card" id="sys">
      <h3>System</h3>
      <div class="row"><div class="k">cpu</div><div class="v" id="cpuv">—</div></div>
      <div class="row"><div class="k">load (1/5/15)</div><div class="v" id="loadv">—</div></div>
      <div class="row"><div class="k">mem</div><div class="v" id="memv">—</div></div>
      <div class="row"><div class="k">disk</div><div class="v" id="diskv">—</div></div>
      <div class="row"><div class="k">temp</div><div class="v" id="tempv">—</div></div>
    </div>

  </div>

  <div class="footer">© Rider-Pi · <a href="/healthz">/healthz</a> · <a href="/state">/state</a> · <a href="/sysinfo">/sysinfo</a></div>
</div>

<script>
const REFRESH_MS = 2000;                       // co ile odświeżamy
const HIST_MAX   = Math.round(60000/REFRESH_MS); // 60 s okno
let cpuHist = [], memHist = [];

function fmt(s){return (s===null||s===undefined)?'—':s}
function cls(val, warn, bad){ if(val==null) return ''; if(val>=bad) return 'bad'; if(val>=warn) return 'warn'; return 'ok'; }

function pushHist(si){
  if(si && si.cpu_pct!=null){ cpuHist.push(si.cpu_pct); if(cpuHist.length>HIST_MAX) cpuHist.shift(); }
  if(si && si.mem_pct!=null){ memHist.push(si.mem_pct); if(memHist.length>HIST_MAX) memHist.shift(); }
}

function drawChart(){
  const c = document.getElementById('hist'); if(!c) return;
  // ensure HiDPI crisp
  const dpr = window.devicePixelRatio||1;
  const w = c.clientWidth, h = c.clientHeight;
  if(c.width !== Math.round(w*dpr)){ c.width = Math.round(w*dpr); c.height = Math.round(h*dpr); }
  const W = c.width, H = c.height, ctx = c.getContext('2d');

  ctx.clearRect(0,0,W,H);
  // grid
  ctx.strokeStyle = 'rgba(255,255,255,0.10)';
  ctx.lineWidth = 1;
  for(let i=1;i<=3;i++){
    const y = H*(i/4);
    ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(W,y); ctx.stroke();
  }
  // helper
  function draw(arr, color){
    if(arr.length<2) return;
    ctx.strokeStyle = color;
    ctx.lineWidth = Math.max(1, dpr);
    ctx.beginPath();
    for(let i=0;i<arr.length;i++){
      const x = i*(W/Math.max(1,arr.length-1));
      const y = H*(1 - (arr[i]/100));
      if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
    }
    ctx.stroke();
  }
  draw(cpuHist, '#f0c36b'); // CPU – żółty
  draw(memHist, '#59a9ff'); // MEM – niebieski
}

async function refresh(){
  try{
    const [h,s,si] = await Promise.all([
      fetch('/healthz', {cache:'no-store'}).then(r=>r.json()),
      fetch('/state',   {cache:'no-store'}).then(r=>r.json()),
      fetch('/sysinfo', {cache:'no-store'}).then(r=>r.json()),
    ]);

    // health
    document.getElementById('h_status').textContent = h.status;
    document.getElementById('h_status').className = (h.status==='ok')?'ok':'bad';
    document.getElementById('h_uptime').textContent = (h.uptime_s||0).toFixed(1)+' s';
    document.getElementById('h_msg').textContent    = fmt(h.bus.last_msg_age_s);
    document.getElementById('h_hb').textContent     = fmt(h.bus.last_heartbeat_age_s);

    // state
    document.getElementById('s_present').textContent = s.present ? 'true':'false';
    document.getElementById('s_present').className = s.present?'ok':'bad';
    document.getElementById('s_conf').textContent  = (s.confidence||0).toFixed(3);
    document.getElementById('s_ts').textContent    = fmt(s.ts);
    document.getElementById('s_age').textContent   = fmt(s.age_s);

    // sysinfo + karty
    if(si){
      const cpu  = (si.cpu_pct!=null)? si.cpu_pct.toFixed(1)+'%' : '—';
      const load = (si.load1!=null)? `${si.load1}/${si.load5}/${si.load15}` : '—';
      const mem  = (si.mem_used_mb!=null)? `${si.mem_used_mb} / ${si.mem_total_mb} MB (${si.mem_pct?.toFixed?si.mem_pct.toFixed(1):si.mem_pct}%)` : '—';
      const dsk  = (si.disk_used_gb!=null)? `${si.disk_used_gb} / ${si.disk_total_gb} GB (${si.disk_pct?.toFixed?si.disk_pct.toFixed(1):si.disk_pct}%)` : '—';
      const tmp  = (si.temp_c!=null)? si.temp_c.toFixed(1)+' °C' : '—';
      const cpuEl = document.getElementById('cpuv');
      cpuEl.textContent = cpu; cpuEl.className = cls(si.cpu_pct, 70, 85);
      document.getElementById('loadv').textContent = load;
      const memEl = document.getElementById('memv');
      memEl.textContent = mem; memEl.className = cls(si.mem_pct, 75, 90);
      const dskEl = document.getElementById('diskv');
      dskEl.textContent = dsk; dskEl.className = cls(si.disk_pct, 80, 90);
      const tEl = document.getElementById('tempv');
      tEl.textContent = tmp; tEl.className = cls(si.temp_c, 65, 75);

      // historia do wykresu
      pushHist(si);
      drawChart();
    }
  }catch(e){}
}
setInterval(refresh, REFRESH_MS);
refresh();
</script>
</body></html>
"""

@app.route("/")
def dashboard():
    return Response(DASHBOARD_HTML, mimetype="text/html", headers={"Cache-Control":"no-store"})

# --- Main ---
if __name__ == "__main__":
    start_sysmon()
    start_bus_sub()
    app.run(host="0.0.0.0", port=STATUS_API_PORT, threaded=True)
