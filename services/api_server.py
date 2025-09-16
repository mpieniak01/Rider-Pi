from flask import Flask, jsonify, make_response, request, send_from_directory
app = Flask(__name__)
import os
import importlib
import traceback
# ── Aliasy / stuby dla zgodności z frontendem ────────────────────────────────
# Alias: /api/last_frame -> /camera/last (GET/HEAD)
def face_ping():
    return jsonify({"ok": True})

def face_render():
    try:
        data = request.get_json(force=True)
        expr = data.get("expr", "neutral")
        rotate = int(data.get("rotate", 0))
        spi_hz = int(data.get("spi_hz", 0))
        backend = data.get("backend", "lcd")
        out = data.get("out", None)
        # Import bez side-effectów
        face_api = importlib.import_module("services.api_core.face_api")
        # Preferuj draw_face jeśli backend lcd, fallback render_face (PNG)
        if backend == "lcd":
            if hasattr(face_api, "draw_face"):
                res, code = face_api.draw_face(data)
                if res.get("ok"):
                    return jsonify(res), code
        # PNG fallback (zawsze dostępny) – nowy backend przez FaceController
        try:
            from apps.ui.face.controller import FaceController
            from PIL import Image
            from io import BytesIO
            fc = FaceController(size=data.get("size", 240), fps=1, idle=True)
            fc.set_expr(expr)
            img = Image.open(BytesIO(fc.frame()))
            if out:
                os.makedirs(os.path.dirname(out), exist_ok=True)
                img.save(out)
                return jsonify({"ok": True, "out": out})
            # Zwróć PNG jako base64
            import base64
            buf = BytesIO(); img.save(buf, "PNG"); png_bytes = buf.getvalue()
            png_b64 = base64.b64encode(png_bytes).decode("ascii")
            return jsonify({"ok": True, "png_b64": png_b64, "expr": expr}), 200
        except Exception as e:
            return jsonify({"ok": False, "error": f"PNG fallback failed: {e}"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "trace": traceback.format_exc()}), 500

app.add_url_rule("/face/ping", view_func=face_ping, methods=["GET"])
app.add_url_rule("/face/render", view_func=face_render, methods=["POST"])



import services.api_core.chat_glue as chat_glue
import services.api_core.services_api as services_api
import services.api_core.dashboard as dashboard
import services.api_core.camera as camera
import services.api_core.voice_proxy as voice_proxy
import services.api_core.control_proxy as control_proxy
import services.api_core.system_info as system_info
import services.api_core.state_api as state_api
import services.api_core.compat as compat



"""
Rider-Pi – API server (router + entrypoint)

- Router mapuje endpointy na moduły z services.api_core.*
"""
import services.api_core.chat_glue as chat_glue
import services.api_core.services_api as services_api
import services.api_core.dashboard as dashboard
import services.api_core.camera as camera
import services.api_core.control_proxy as control_proxy
import services.api_core.system_info as system_info
import services.api_core.state_api as state_api
import services.api_core.compat as compat



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
# Idempotentna rejestracja tras: /api/chat/history (GET, OPTIONS), /api/chat/send (POST, OPTIONS)
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
