"""Direct RGB rendering with one cached frame and lazy, shared PNG encoding."""

from io import BytesIO

from PIL import Image, ImageDraw

from apps.draw.face_primitives import draw_face
from apps.ui.face.characters import SKINS, draw_character
from apps.ui.face.friendly import PALETTES, draw_friendly
from apps.ui.face.professional import draw_professional

STYLES = ("friendly", "minimal", "legacy")


class FaceRenderer:
    def __init__(self, cfg, size=240, guide=False, quality="fast", style=None, skin=None):
        self.cfg, self.size, self.guide, self.quality = cfg, size, guide, quality
        self.style = style or (cfg.get("style", "legacy") if isinstance(cfg, dict) else "legacy")
        self.skin = skin or (cfg.get("skin", "none") if isinstance(cfg, dict) else "none")
        self._background = None
        self._background_style = None
        self._key = self._image = self._png = None
        self.last_changed = False
        self.render_count = self.encode_count = 0

    def _state_key(self, state):
        values = [self.style, self.skin, self.guide, state.expr]
        for node, fields in (
            ("eyes", ("dx", "dy", "blink")),
            ("brows", ("lift", "tilt")),
            ("mouth", ("open", "shape", "curve")),
        ):
            obj = getattr(state, node, None)
            for field in fields:
                value = getattr(obj, field, None)
                values.append(round(value, 4) if isinstance(value, (int, float)) else value)
        if self.style == "legacy" and self.skin != "professional":
            values.append(getattr(state, "render_time", None))
        return tuple(values)

    def render_image(self, state=None, face_state=None):
        state = state if state is not None else face_state
        if self.style not in STYLES:
            raise ValueError("invalid_face_style")
        if self.skin not in SKINS:
            raise ValueError("invalid_face_skin")
        key = self._state_key(state)
        self.last_changed = key != self._key or self._image is None
        if self.last_changed:
            background_key = (self.style, self.skin)
            if self._background_style != background_key:
                color = PALETTES[self.style]["background"] if self.style != "legacy" else (30, 58, 138)
                background_size = self.size * 2 if self.skin == "professional" else self.size
                self._background = Image.new("RGB", (background_size, background_size), color)
                draw_character(ImageDraw.Draw(self._background), self.skin)
                if background_size != self.size:
                    self._background = self._background.resize((self.size, self.size), Image.Resampling.LANCZOS)
                self._background_style = background_key
            img = self._background.copy()
            canvas = ImageDraw.Draw(img)
            if self.skin == "professional":
                draw_professional(canvas, state, self.style)
            elif self.style == "legacy":
                draw_face(canvas, self.cfg, state, guide=self.guide, quality=self.quality)
            else:
                draw_friendly(canvas, state, self.style, self.skin)
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
