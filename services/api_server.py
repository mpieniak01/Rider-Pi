from flask import Flask, jsonify, request, make_response
import os
import traceback  # zostawione do debugowania

# Nowy shim dla buźki (PNG/file + 503 dla LCD bez HW)
from services.api_core.face_api import render_face as face_render_shim

# Moduły API (utrzymane dla spójności systemu)
import services.api_core.chat_glue as chat_glue
import services.api_core.services_api as services_api
import services.api_core.dashboard as dashboard
import services.api_core.camera as camera
import services.api_core.voice_proxy as voice_proxy
import services.api_core.control_proxy as control_proxy
import services.api_core.system_info as system_info
import services.api_core.state_api as state_api
import services.api_core.compat as compat

app = Flask(__name__)

# ── Helpers (MUSZĄ być zdefiniowane PRZED użyciem) ───────────────────────────
def _corsify(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return resp

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

# ── Legacy: /api/draw/face (stary endpoint) ──────────────────────────────────
@app.route("/api/draw/face", methods=["POST", "OPTIONS"])
def api_draw_face_legacy():
    # CORS preflight
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))

    payload = request.get_json(force=True, silent=True) or {}
    # shim w face_api zwraca (body, http_status)
    from services.api_core.face_api import draw_face
    body, status = draw_face(payload)
    return _corsify(make_response(jsonify(body), status))

# ── Voice proxy ──────────────────────────────────────────────────────────────
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

# ── Chat API (/api/chat/*) ───────────────────────────────────────────────────
try:
    chat_glue.register(app)
    app.logger.info("Chat API registered at /api/chat/*")
except Exception as e:
    app.logger.warning(f"Chat API not available: {e}")

# ── Aliasy / stuby dla zgodności z frontendem ────────────────────────────────
def _api_last_frame():
    return camera.camera_last()
app.add_url_rule("/api/last_frame", view_func=_api_last_frame, methods=["GET", "HEAD"])

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
