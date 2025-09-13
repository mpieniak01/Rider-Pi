from __future__ import annotations

from typing import Tuple

try:
    from PIL import Image, ImageDraw
except Exception:  # pragma: no cover - optional dependency
    Image = None
    ImageDraw = None

GREEN = (0, 255, 0)
BLACK = (0, 0, 0)


def new_canvas(size: int) -> "Image.Image":
    if Image is None:
        raise RuntimeError("Pillow not available")
    return Image.new("RGB", (size, size), BLACK)


def draw_head(d: "ImageDraw.ImageDraw", cx: int, cy: int, r: int) -> None:
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=GREEN, width=3)


def draw_eyes(d: "ImageDraw.ImageDraw", cx: int, cy: int, size: int) -> None:
    eye_y = cy - size // 6
    eye_dx = size // 6
    for ex in (cx - eye_dx, cx + eye_dx):
        d.ellipse((ex - 12, eye_y - 12, ex + 12, eye_y + 12), fill=GREEN)


def draw_mouth(
    d: "ImageDraw.ImageDraw", cx: int, cy: int, size: int, kind: str
) -> None:
    if kind == "happy":
        d.arc((cx - 60, cy, cx + 60, cy + 60), start=200, end=340, fill=GREEN, width=4)
    elif kind == "sad":
        d.arc((cx - 60, cy - 20, cx + 60, cy + 40), start=20, end=160, fill=GREEN, width=4)
    else:
        d.line((cx - 60, cy + 30, cx + 60, cy + 30), fill=GREEN, width=4)
