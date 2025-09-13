from __future__ import annotations
import io, base64
from PIL import ImageDraw
from .face_primitives import new_canvas, draw_head, draw_eyes, draw_mouth
from .face_emotions import normalize_expr

def render_face(expr: str = "neutral", size: int = 240) -> bytes:
    expr = normalize_expr(expr)
    img = new_canvas(size)
    d = ImageDraw.Draw(img)

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
