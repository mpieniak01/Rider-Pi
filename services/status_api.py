##!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rider-Pi – Status API (entrypoint + routing only)
Handlery siedzą w services.status_core
"""

import services.status_core as core
from flask import Response

# pobierz obiekty z core w sposób bezpieczny
app = getattr(core, "app", None)
if app is None:
    # ostatnia deska ratunku — tworzymy Flask, ale lepiej mieć app w core
    from flask import Flask
    app = Flask(__name__)

STATUS_API_PORT = int(getattr(core, "STATUS_API_PORT", 8080))

# ======= ROUTES =======

@app.route("/healthz")
def _r_healthz():          return core.healthz()

@app.route("/health")
def _r_health_alias():     return core.health_alias()

@app.route("/state")
def _r_state():            return core.state()

@app.route("/sysinfo")
def _r_sysinfo():          return core.sysinfo()

@app.route("/metrics")
def _r_metrics():          return core.metrics()

@app.route("/events")
def _r_events():           return core.events()

# Kamera / snapshots
@app.route("/camera/raw",  methods=["GET","HEAD"])
def _r_camera_raw():       return core.camera_raw()

@app.route("/camera/proc", methods=["GET","HEAD"])
def _r_camera_proc():      return core.camera_proc()

@app.route("/camera/last", methods=["GET","HEAD"])
def _r_camera_last():      return core.camera_last()

@app.route("/camera/placeholder", methods=["GET","HEAD"])
def _r_camera_placeholder(): return core.camera_placeholder()

@app.route("/snapshots/<path:fname>")
def _r_snapshots(fname):   return core.snapshots_static(fname)

# Services
@app.route("/svc", methods=["GET"])
def _r_svc_list():         return core.svc_list()

@app.route("/svc/<name>/status", methods=["GET"])
def _r_svc_status(name):   return core.svc_status(name)

@app.route("/svc/<name>", methods=["POST"])
def _r_svc_action(name):   return core.svc_action(name)

# Dashboard (z bezpiecznym fallbackiem)
@app.route("/")
def _r_dashboard():
    if hasattr(core, "dashboard"):
        return core.dashboard()
    return Response(
        "<h1>Rider-Pi API</h1>"
        "<p>Brak web/view.html lub dashboard() w core – użyj "
        "<a href='/state'>/state</a>, <a href='/sysinfo'>/sysinfo</a>, "
        "<a href='/healthz'>/healthz</a>.</p>",
        mimetype="text/html"
    ), 200

@app.route("/control")
def _r_control():
    if hasattr(core, "control_page"):
        return core.control_page()
    return Response("<h1>control.html missing</h1>", mimetype="text/html"), 404

# Komendy
@app.route("/api/move",  methods=["POST"])
def _r_api_move():         return core.api_move()

@app.route("/api/stop",  methods=["POST"])
def _r_api_stop():         return core.api_stop()

@app.route("/api/preset",methods=["POST"])
def _r_api_preset():       return core.api_preset()

@app.route("/api/voice", methods=["POST"])
def _r_api_voice():        return core.api_voice()

@app.route("/api/cmd",   methods=["POST"])
def _r_api_cmd():         return core.api_cmd()

# ======= BOOTSTRAP =======
if __name__ == "__main__":
    # Spróbuj wystartować wątki z core, jeśli istnieją
    for fn_name in ("start_bus_sub", "start_xgo_ro"):
        fn = getattr(core, fn_name, None)
        if callable(fn):
            try:
                fn()
            except Exception as e:
                print(f"[api] {fn_name} failed:", e, flush=True)

    app.run(host="0.0.0.0", port=STATUS_API_PORT, threaded=True)
