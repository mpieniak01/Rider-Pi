from __future__ import annotations

import base64
import io
from typing import Any, Dict

from .face_emotions import normalize_expr
from .face_primitives import draw_eyes, draw_head, draw_mouth, new_canvas


def render_face(expr: str = "neutral", size: int = 240) -> bytes:
    expr = normalize_expr(expr)
    img = new_canvas(size)
    d = __import__("PIL.ImageDraw").ImageDraw.Draw(img)
    cx, cy, r = size // 2, size // 2, size // 2 - 6
    draw_head(d, cx, cy, r)
    draw_eyes(d, cx, cy, size)
    mouth = "happy" if expr == "happy" else ("sad" if expr == "sad" else "neutral")
    draw_mouth(d, cx, cy, size, mouth)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def to_b64(png_bytes: bytes) -> str:
    return base64.b64encode(png_bytes).decode("ascii")
