from __future__ import annotations
from typing import Any, Dict, Tuple

from apps.ui.face.renderer import FaceRenderer
from apps.hw.sink_lcd import SinkLCD
import base64
import os

ALLOWED = {"happy", "sad", "neutral", "blink"}

def to_b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")

def draw_face(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    try:
        expr = str(payload.get("expr", "neutral")).lower()
        size = int(payload.get("size", 240))
        sink = str(payload.get("sink", "none")).lower()  # lcd|file|none
        rotate = payload.get("rotate")
        spi_hz = payload.get("spi_hz")
        file_path = payload.get("file_path", "face_out.png")
        if expr not in ALLOWED:
            return {"ok": False, "error": "bad expr"}, 400
        if not (64 <= size <= 480):
            return {"ok": False, "error": "bad size"}, 400

        # Dummy FaceState for demo (w docelowej wersji: z modelu)
        class DummyFaceState:
            def blink_mul(self): return 1.0
            state = expr
            gaze_dx = 0
            expr = expr
            expr_intensity = 0.0
            assist_speaking = False
            speak_phase = 0.0

        cfg = type("Cfg", (), {"mouth_y_k": 0.215, "brow_y_k": 0.21, "brow_h_k": 0.09, "head_ky": 1.04})()
        renderer = FaceRenderer(cfg, size=size)
        png_bytes = renderer.render_png_bytes(DummyFaceState())

        if sink == "lcd":
            lcd = SinkLCD(width=size, height=size, rotate=rotate, spi_hz=spi_hz)
            from PIL import Image
            img = Image.open(BytesIO(png_bytes))
            try:
                lcd.show_image(img)
                return {"ok": True, "sink": "lcd", "expr": expr, "size": size}, 200
            except Exception as e:
                return {"ok": False, "error": f"lcd error: {e}"}, 500
        elif sink == "file":
            with open(file_path, "wb") as f:
                f.write(png_bytes)
            return {"ok": True, "sink": "file", "file": file_path, "expr": expr, "size": size}, 200
        else:
            return {"ok": True, "png_b64": to_b64(png_bytes), "expr": expr, "size": size}, 200
    except Exception as e:
        return {"ok": False, "error": f"render failed: {e.__class__.__name__}: {e}"}, 500
