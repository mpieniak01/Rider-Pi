from __future__ import annotations
from typing import Any, Dict, Tuple

import os
from apps.draw.face_renderer import render_face, to_b64
from typing import Any, Dict, Tuple
from PIL import Image
from io import BytesIO
import base64

ALLOWED = {"happy", "sad", "neutral", "blink"}


def draw_face(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """
    API: renderuj buźkę na PNG lub LCD (RAW). Param: backend=png|lcd (default: png).
    LCD: lazy import HW, 503 gdy brak HW.
    """
    try:
        expr = str(payload.get("expr", "neutral")).lower()
        size = int(payload.get("size", 240))
        backend = payload.get("backend", "png")
        if expr not in ALLOWED:
            return {"ok": False, "error": "bad expr"}, 400
        if not (64 <= size <= 480):
            return {"ok": False, "error": "bad size"}, 400
        if backend == "lcd":
            # Lazy import HW, fallback 503 jeśli brak HW
            try:
                from tools.newface_lcd_direct import LCDDirect
                from apps.ui.face.controller import FaceController
                fc = FaceController(size=size, fps=1, idle=True)
                fc.set_expr(expr)
                img = Image.open(BytesIO(fc.frame())).convert("RGB")
                lcd = LCDDirect(rotate=int(payload.get("rotate", os.getenv("FACE_LCD_ROTATE", 0))),
                                size=size,
                                spi_hz=int(payload.get("spi_hz", os.getenv("FACE_LCD_SPI_HZ", 0)) or 0),
                                bl_pin=int(payload.get("bl_pin", os.getenv("FACE_LCD_BL_PIN", 13))),
                                force="raw")
                how = lcd.push(img)
                return {"ok": True, "backend": "lcd", "how": how, "expr": expr, "size": size}, 200
            except Exception as e:
                return {"ok": False, "error": f"LCD unavailable: {e}", "backend": "lcd"}, 503
        # PNG fallback (zawsze dostępny)
        png = render_face(expr=expr, size=size)
        return {"ok": True, "png_b64": to_b64(png), "expr": expr, "size": size, "backend": "png"}, 200
    except Exception as e:
        return {"ok": False, "error": f"render failed: {e.__class__.__name__}: {e}"}, 500
