from __future__ import annotations
import io, base64
from PIL import ImageDraw
## Usunięto importy do nieistniejących funkcji (new_canvas, draw_head, draw_eyes, draw_mouth)
from .face_emotions import normalize_expr


def render_face(*args, **kwargs):
    raise NotImplementedError(
        "render_face: funkcja nie jest już wspierana w nowej architekturze. Użyj FaceRenderer."
    )

def to_b64(png_bytes: bytes) -> str:
    return base64.b64encode(png_bytes).decode("ascii")
