from __future__ import annotations

"""
apps/ui/face/renderer.py — czysty renderer PNG dla buźki Rider-Pi.
Wejście: FaceState, wyjście: PNG bytes.
Brak cyklicznych zależności (nie importuje controller ani LCD).
"""

from io import BytesIO  # noqa: E402

from PIL import Image, ImageDraw  # noqa: E402

from apps.draw.face_primitives import draw_face  # noqa: E402


class FaceRenderer:
    def __init__(self, cfg, size=240, guide=False, quality="fast"):
        self.cfg = cfg
        self.size = size
        self.guide = guide
        self.quality = quality

    def render_png_bytes(self, face_state) -> bytes:
        """
        Renderuje buźkę do PNG bytes.
        :param face_state: obiekt FaceState lub podobny
        :return: PNG bytes
        """
        img = Image.new("RGB", (self.size, self.size), (30, 58, 138))
        canvas = ImageDraw.Draw(img)
        draw_face(canvas, self.cfg, face_state, guide=self.guide, quality=self.quality)
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
