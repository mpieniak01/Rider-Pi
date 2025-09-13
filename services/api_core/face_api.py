from __future__ import annotations

from typing import Any, Dict, Tuple

from apps.draw.face_renderer import render_face, to_b64

ALLOWED = {"happy", "sad", "neutral", "blink"}


def draw_face(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    expr = str(payload.get("expr", "neutral")).lower()
    size = int(payload.get("size", 240))
    if expr not in ALLOWED:
        return {"ok": False, "error": "bad expr"}, 400
    if not (64 <= size <= 480):
        return {"ok": False, "error": "bad size"}, 400
    png = render_face(expr=expr, size=size)
    return {"ok": True, "png_b64": to_b64(png), "expr": expr, "size": size}, 200
