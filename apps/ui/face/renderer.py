"""Direct RGB rendering with one cached frame and lazy, shared PNG encoding."""

from io import BytesIO

from PIL import Image, ImageDraw

from apps.draw.face_primitives import draw_face
from apps.ui.face.friendly import PALETTES, draw_friendly

STYLES = ("friendly", "minimal", "legacy")


class FaceRenderer:
    def __init__(self, cfg, size=240, guide=False, quality="fast", style=None):
        self.cfg, self.size, self.guide, self.quality = cfg, size, guide, quality
        self.style = style or (cfg.get("style", "legacy") if isinstance(cfg, dict) else "legacy")
        self._background = None
        self._background_style = None
        self._key = self._image = self._png = None
        self.last_changed = False
        self.render_count = self.encode_count = 0

    def _state_key(self, state):
        values = [self.style, self.guide, state.expr]
        for node, fields in (
            ("eyes", ("dx", "dy", "blink")),
            ("brows", ("lift", "tilt")),
            ("mouth", ("open", "shape", "curve")),
        ):
            obj = getattr(state, node, None)
            for field in fields:
                value = getattr(obj, field, None)
                values.append(round(value, 4) if isinstance(value, (int, float)) else value)
        if self.style == "legacy":
            values.append(getattr(state, "render_time", None))
        return tuple(values)

    def render_image(self, state=None, face_state=None):
        state = state if state is not None else face_state
        if self.style not in STYLES:
            raise ValueError("invalid_face_style")
        key = self._state_key(state)
        self.last_changed = key != self._key or self._image is None
        if self.last_changed:
            if self._background_style != self.style:
                color = PALETTES[self.style]["background"] if self.style != "legacy" else (30, 58, 138)
                self._background = Image.new("RGB", (self.size, self.size), color)
                self._background_style = self.style
            img = self._background.copy()
            canvas = ImageDraw.Draw(img)
            if self.style == "legacy":
                draw_face(canvas, self.cfg, state, guide=self.guide, quality=self.quality)
            else:
                draw_friendly(canvas, state, self.style)
            self._key, self._image, self._png = key, img, None
            self.render_count += 1
        return self._image.copy()

    def render_png_bytes(self, face_state) -> bytes:
        self.render_image(face_state)
        if self._png is None:
            buf = BytesIO()
            self._image.save(buf, format="PNG")
            self._png = buf.getvalue()
            self.encode_count += 1
        return self._png
