from flask import Flask, jsonify, request
import os
import traceback

# New face shim (PNG/file + 503 dla LCD bez HW)
from services.api_core.face_api import render_face as face_render_shim

# Moduły API
import services.api_core.chat_glue as chat_glue
import services.api_core.services_api as services_api   # zostawione dla spójności
import services.api_core.dashboard as dashboard         # jw.
import services.api_core.camera as camera
import services.api_core.voice_proxy as voice_proxy
import services.api_core.control_proxy as control_proxy
import services.api_core.system_info as system_info
import services.api_core.state_api as state_api
import services.api_core.compat as compat

app = Flask(__name__)

# ── Face API (nowe) ──────────────────────────────────────────────────────────
@app.route("/face/ping", methods=["GET"])
def face_ping():
    return jsonify({"ok": True})

@app.route("/face/render", methods=["POST"])
def face_render():
    payload = request.get_json(force=True, silent=True) or {}
    res = face_render_shim(payload)
    # Przekładaj 503 dla LCD bez HW
    status = 503 if (not res.get("ok") and res.get("status") == 503) else 200
    return jsonify(res), status

# ── Voice proxy ─────────────────────────────────────────────────────────────
app.add_url_rule(
    "/api/voice/capture",
    view_func=voice_proxy.capture_handler,
    methods=["POST", "OPTIONS"],
)
app.add_url_rule(
    "/api/voice/say",
    view_func=voice_proxy.say_handler,
    methods=["POST", "OPTIONS"],
)

# ── Chat API (/api/chat/*) ──────────────────────────────────────────────────
try:
    chat_glue.register(app)
    app.logger.info("Chat API registered at /api/chat/*")
except Exception as e:
    app.logger.warning(f"Chat API not available: {e}")

# ── Aliasy / stuby dla zgodności z frontendem ────────────────────────────────
# Alias: /api/last_frame -> /camera/last (GET/HEAD)
def _api_last_frame():
    return camera.camera_last()
app.add_url_rule("/api/last_frame", view_func=_api_last_frame, methods=["GET", "HEAD"])

# Stub: /api/bus/health (GET/OPTIONS) – zwraca OK, aby nie spamować logów
def _bus_health():
    if request.method == "OPTIONS":
        return (
            "",
            204,
            {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
            },
        )
    return (jsonify({"ok": True}), 200, {"Access-Control-Allow-Origin": "*"})

app.add_url_rule("/api/bus/health", view_func=_bus_health, methods=["GET", "OPTIONS"])

# Stub: /vision/obstacle (GET) – jeśli moduł nieaktywny
def _vision_obstacle_stub():
    return jsonify({"ok": False, "error": "vision obstacle not enabled"}), 404
app.add_url_rule("/vision/obstacle", view_func=_vision_obstacle_stub, methods=["GET"])

# ── BOOTSTRAP ────────────────────────────────────────────────────────────────
def main():
    compat.start_bus_sub()
    compat.start_xgo_ro()
    port = int(os.environ.get("STATUS_API_PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    main()

# ── Helpers ─────────────────────────────────────────────────────────────────
def _corsify(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return resp
