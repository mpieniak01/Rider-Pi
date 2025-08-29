#!/usr/bin/env python3
# Minimalne API: /healthz i /state (kompatybilne z Flask 1.x i 2.x)
import os, time, json, threading
from typing import Any, Dict
from flask import Flask, jsonify, Response

try:
    import zmq
except Exception:
    zmq = None

BUS_SUB_PORT = int(os.getenv("BUS_SUB_PORT", "5556"))
STATUS_API_PORT = int(os.getenv("STATUS_API_PORT", "8080"))

app = Flask(__name__)

# kompatybilny dekorator GET (Flask 1.x nie ma app.get)
def route_get(path):
    if hasattr(app, "get"):
        return app.get(path)
    return app.route(path, methods=["GET"])

_last_state: Dict[str, Any] = {"present": False, "confidence": 0.0, "ts": None}
_last_msg_ts: float = 0.0
_last_hb_ts: float = 0.0
_start_ts: float = time.time()

def _sub_loop():
    """Subskrybuje vision.* z busa i aktualizuje ostatni stan/heartbeat."""
    global _last_state, _last_msg_ts, _last_hb_ts
    if zmq is None:
        print("[api] pyzmq not available; bus disabled", flush=True)
        return
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.SUB)
    s.connect(f"tcp://127.0.0.1:{BUS_SUB_PORT}")
    s.setsockopt_string(zmq.SUBSCRIBE, "vision.")
    print(f"[api] SUB connected tcp://127.0.0.1:{BUS_SUB_PORT}", flush=True)
    while True:
        try:
            msg = s.recv_string()
            topic, payload = msg.split(" ", 1)
            print(f"[api] got: {topic}", flush=True)
            now = time.time()
            _last_msg_ts = now
            try:
                data = json.loads(payload)
            except Exception:
                data = {}
            if topic == "vision.state":
                _last_state = {
                    "present": bool(data.get("present", False)),
                    "confidence": float(data.get("confidence", 0.0)),
                    "ts": float(data.get("ts", now)),
                }
            elif topic == "vision.dispatcher.heartbeat":
                _last_hb_ts = now
        except Exception:
            time.sleep(0.05)

@route_get("/healthz")
def healthz():
    now = time.time()
    hb_age = None if _last_hb_ts == 0 else now - _last_hb_ts
    msg_age = None if _last_msg_ts == 0 else now - _last_msg_ts
    bus_ok = (hb_age is not None and hb_age < 10.0) or (msg_age is not None and msg_age < 10.0)
    return jsonify({
        "status": "ok" if bus_ok else "degraded",
        "uptime_s": round(now - _start_ts, 3),
        "bus": {
            "last_msg_age_s": None if msg_age is None else round(msg_age, 3),
            "last_heartbeat_age_s": None if hb_age is None else round(hb_age, 3),
        },
    })

@route_get("/state")
def state():
    now = time.time()
    ts = _last_state.get("ts")
    age = None if ts is None else max(0.0, now - float(ts))
    return jsonify({
        "present": bool(_last_state.get("present", False)),
        "confidence": float(_last_state.get("confidence", 0.0)),
        "ts": ts,
        "age_s": None if age is None else round(age, 3),
    })

def main():
    threading.Thread(target=_sub_loop, daemon=True).start()
    # Flask 1.x/2.x kompatybilnie:
    app.run(host="0.0.0.0", port=STATUS_API_PORT, threaded=True, use_reloader=False)


# --- Mini dashboard (HTML) ---
DASHBOARD_HTML = """<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8">
  <title>Rider-Pi — Status</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root { font-family: system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, 'Helvetica Neue', Arial, 'Noto Sans', 'Apple Color Emoji', 'Segoe UI Emoji', 'Segoe UI Symbol'; }
    body { margin: 0; padding: 24px; background:#0b1020; color:#e7eaf6; }
    .wrap { max-width: 960px; margin: 0 auto; }
    h1 { margin: 0 0 16px; font-weight: 700; }
    .muted { color:#9aa4c7; font-size: 14px; }
    .grid { display:grid; grid-template-columns: repeat(auto-fit,minmax(260px,1fr)); gap:16px; margin-top:16px; }
    .card { background:#151b34; border:1px solid #263056; border-radius:14px; padding:16px; box-shadow: 0 6px 18px rgba(0,0,0,.25); }
    .k { color:#9aa4c7; }
    .v { font-variant-numeric: tabular-nums; font-weight:600; }
    .ok { color:#6ee7a0; }
    .bad { color:#ff788a; }
    .warn{ color:#ffd166; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono","Courier New", monospace; }
    .row { display:flex; justify-content: space-between; gap:8px; margin:6px 0; }
    .footer { margin-top: 18px; font-size: 12px; color:#6b748f; }
    a { color:#8ab4ff; text-decoration: none; }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Rider-Pi — mini dashboard</h1>
    <div class="muted">Auto-refresh co 2 s. Endpointy: <span class="mono">/healthz</span>, <span class="mono">/state</span></div>

    <div class="grid">
      <div class="card" id="health">
        <h3>Health</h3>
        <div class="row"><div class="k">status</div><div class="v" id="st">—</div></div>
        <div class="row"><div class="k">uptime</div><div class="v" id="up">—</div></div>
        <div class="row"><div class="k">bus.last_msg_age</div><div class="v" id="lma">—</div></div>
        <div class="row"><div class="k">bus.last_heartbeat_age</div><div class="v" id="lha">—</div></div>
      </div>

      <div class="card" id="presence">
        <h3>Presence (vision.state)</h3>
        <div class="row"><div class="k">present</div><div class="v" id="pr">—</div></div>
        <div class="row"><div class="k">confidence</div><div class="v" id="cf">—</div></div>
        <div class="row"><div class="k">ts</div><div class="v" id="ts">—</div></div>
        <div class="row"><div class="k">age</div><div class="v" id="ag">—</div></div>
      </div>
    </div>

    <div class="footer">© Rider-Pi • <a href="/healthz" class="mono">/healthz</a> • <a href="/state" class="mono">/state</a></div>
  </div>

<script>
function fmtAge(x){ if(x===null||x===undefined) return "—"; try{ let s=Number(x); if(isNaN(s)) return "—"; if(s<1) return (s*1000).toFixed(0)+" ms"; if(s<60) return s.toFixed(1)+" s"; let m=Math.floor(s/60), r=s%60; return m+" min "+r.toFixed(0)+" s"; }catch(e){return "—";}}
function fmtNum(x, d=3){ if(x===null||x===undefined) return "—"; let n=Number(x); if(isNaN(n)) return "—"; return n.toFixed(d); }
function fmtTs(ts){ if(!ts) return "—"; try{ let d=new Date(ts*1000); return d.toLocaleString(); } catch(e){ return "—"; } }

async function refresh(){
  try{
    const [h,s] = await Promise.all([
      fetch('/healthz', {cache:'no-store'}).then(r=>r.json()),
      fetch('/state',   {cache:'no-store'}).then(r=>r.json())
    ]);
    // health
    const st = document.getElementById('st');
    st.textContent = h.status || "—";
    st.className = (h.status==="ok")? "v ok" : (h.status==="degraded")? "v warn":"v bad";
    document.getElementById('up').textContent  = fmtAge(h.uptime_s);
    document.getElementById('lma').textContent = fmtAge(h.bus && h.bus.last_msg_age_s);
    document.getElementById('lha').textContent = fmtAge(h.bus && h.bus.last_heartbeat_age_s);
    // state
    const present = !!s.present;
    const pr = document.getElementById('pr');
    pr.textContent = present ? "true" : "false";
    pr.className = present ? "v ok" : "v bad";
    document.getElementById('cf').textContent = fmtNum(s.confidence ?? 0.0, 3);
    document.getElementById('ts').textContent = fmtTs(s.ts);
    document.getElementById('ag').textContent = fmtAge(s.age_s);
  }catch(e){
    document.getElementById('st').textContent = "error"; document.getElementById('st').className="v bad";
  }
}

refresh();
setInterval(refresh, 2000);
</script>
</body></html>
"""

@app.route("/")
def dashboard():
    return Response(DASHBOARD_HTML, mimetype="text/html")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
