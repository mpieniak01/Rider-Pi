from __future__ import annotations
import io, math, time
from typing import Tuple
from PIL import Image, ImageDraw
from .model import FaceState

# --- Kolory ---
FACE_BG = (8, 36, 70)
NEON    = (255, 0, 0)
WHITE   = (255, 255, 255)
BLACK   = (0, 0, 0)

# --- Stałe geometrii (przeniesione ze starego _apps) ---
EYE_DX_K   = 0.22   # odległość oka od środka (×S)
EYE_W_K    = 0.28   # szerokość oka (×S)
EYE_H_K    = 0.12   # wysokość oka (×S) — mnożona przez blink_mul
MOUTH_W_K  = 0.58   # szerokość ust (×S)
MOUTH_Y_K  = 0.215  # przesunięcie ust w dół od środka (×S)
HEAD_KY    = 1.04   # elipsa głowy (1.0 = koło)

def _clamp(v, a, b):
    return a if v < a else b if v > b else v


class FaceRenderer:
    """Port starego rysowania (oczy/mrugnięcie/usta) do nowej architektury."""
    def __init__(self, size: int = 240):
        self.size = size

    # --- Geometria wspólna ---
    def _face_geom(self):
        cx = cy = self.size // 2
        S  = min(self.size, self.size)
        eye_dx  = int(S * EYE_DX_K)
        eye_w   = int(S * EYE_W_K)
        eye_h   = int(S * EYE_H_K)
        mouth_w = int(S * MOUTH_W_K)
        mouth_y = int(cy + S * MOUTH_Y_K)
        return cx, cy, S, eye_dx, eye_w, eye_h, mouth_w, mouth_y

    def _draw_head(self, d: ImageDraw.ImageDraw) -> None:
        cx = cy = self.size // 2
        r  = self.size // 2 - 6
        # tło + okrąg
        d.rectangle((0, 0, self.size, self.size), fill=FACE_BG)
        # dla HEAD_KY != 1.0 rysujemy elipsę z ograniczeniem do wysokości
        ry_limit = r
        rx = r
        ry = int(min(ry_limit, rx * HEAD_KY))
        d.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), outline=NEON, width=4)

    # --- Oczy + mrugnięcie (jak w starym rendererze) ---
    def _draw_eyes(self, d: ImageDraw.ImageDraw, st: FaceState, S: int, cx: int, cy: int, eye_dx: int, eye_w: int, eye_h: int) -> None:
        # blink_mul 1.0 = otwarte; 0.25 = zamknięte; 0.6 = after-blink
        # U nas steruje tym st.eyes.blink (0..1) → mapujemy na 1..0.25
        b = _clamp(st.eyes.blink, 0.0, 1.0)
        blink_mul = 1.0 - 0.75 * b

        # białka
        l = (cx - eye_dx - eye_w // 2, cy - int(eye_h * blink_mul), cx - eye_dx + eye_w // 2, cy + int(eye_h * blink_mul))
        r = (cx + eye_dx - eye_w // 2, cy - int(eye_h * blink_mul), cx + eye_dx + eye_w // 2, cy + int(eye_h * blink_mul))
        d.ellipse(l, fill=WHITE)
        d.ellipse(r, fill=WHITE)

        # źrenice — wysokość też ~ blink_mul, więc nigdy nie „wychodzą” poza białko
        def pupil_rect(rect, x_off_px):
            x1, y1, x2, y2 = rect
            ex, ey = (x1 + x2) // 2, (y1 + y2) // 2
            pw = int(eye_w * 0.18)
            ph = int(eye_h * 0.6 * blink_mul + 2)
            return (ex - pw // 2 + x_off_px, ey - ph // 2, ex + pw // 2 + x_off_px, ey + ph // 2)

        # mikrosakkady jak kiedyś (delikatny sinus + bias)
        t = time.time()
        freq = 1.6
        amp  = eye_w * 0.04
        phase = 0.35
        bias = int(S * 0.017)
        # sterowanie z modelu (st.eyes.dx/dy) — dosuwamy jako piksele
        gaze_px = int(_clamp(st.eyes.dx, -1, 1) * eye_w * 0.25)
        offL = int(math.sin(t * freq) * amp + gaze_px)
        offR = int(math.sin(t * freq + phase) * amp + gaze_px)

        d.ellipse(pupil_rect(l,  +bias + offL), fill=BLACK)
        d.ellipse(pupil_rect(r,  -bias + offR), fill=BLACK)

        # brwi — proste łuki (jak w nowej wersji), zostawiamy z dotychczasowego kodu:
        # (możemy później przenieść również pełny styl brwi ze starego rendererka)
        lift = _clamp(st.brows.lift, -1, 1)
        tilt = _clamp(st.brows.tilt, -1, 1)
        raise_px = int(eye_h * 1.0 * lift)
        brow_r = int(eye_w * 1.2)
        bx_off = int(eye_w * 0.10)

        # lewa
        x0, y0, x1, y1 = (cx - eye_dx - bx_off - brow_r, cy - eye_h - raise_px - int(eye_h*1.3),
                          cx - eye_dx - bx_off + brow_r, cy - eye_h - raise_px + int(eye_h*0.1))
        d.arc((x0, y0, x1, y1), 200 + int(10*tilt), 340 + int(10*tilt), fill=WHITE, width=3)
        # prawa
        x0, y0, x1, y1 = (cx + eye_dx + bx_off - brow_r, cy - eye_h - raise_px - int(eye_h*1.3),
                          cx + eye_dx + bx_off + brow_r, cy - eye_h - raise_px + int(eye_h*0.1))
        d.arc((x0, y0, x1, y1), 200 - int(10*tilt), 340 - int(10*tilt), fill=WHITE, width=3)

    # --- Usta (jak w starym rendererze) ---
    def _draw_mouth(self, d: ImageDraw.ImageDraw, st: FaceState, S: int, cx: int, mouth_w: int, mouth_y: int) -> None:
        def mouth_k_for(expr: str) -> float:
            # wartości bazowe ze starego kodu (delikatnie uproszczone)
            base = {
                "happy":  -0.28,
                "neutral": -0.18,
                "sad":     +0.28,
            }.get((expr or "").lower(), -0.24)
            return base

        k = mouth_k_for(st.expr)
        depth = max(6, int(abs(k) * S * 0.28))
        x0, y0, x1, y1 = cx - mouth_w // 2, mouth_y - depth, cx + mouth_w // 2, mouth_y + depth
        if k < 0:
            start, end = 20, 160   # ∪
        else:
            start, end = 200, 340  # ∩
        d.arc((x0, y0, x1, y1), start=start, end=end, fill=BLACK, width=max(6, int(S * 0.055)))

        # „mowa” — jeśli mouth.open > 0 → prostokąt jak dawniej
        if st.mouth.open > 0:
            height = max(6, int(S * 0.04) + int(st.mouth.open * (S * 0.06)))
            width  = int(mouth_w * (1.0 + 0.06 * st.mouth.open))
            d.rectangle((cx - width//2, mouth_y - height//2, cx + width//2, mouth_y + height//2), fill=BLACK)

    # --- render ---
    def render(self, state: FaceState) -> bytes:
        img = Image.new("RGB", (self.size, self.size), FACE_BG)
        d = ImageDraw.Draw(img)

        self._draw_head(d)
        cx, cy, S, eye_dx, eye_w, eye_h, mouth_w, mouth_y = self._face_geom()
        self._draw_eyes(d, state, S, cx, cy, eye_dx, eye_w, eye_h)
        self._draw_mouth(d, state, S, cx, mouth_w, mouth_y)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


def render_face(state: FaceState, size: int = 240) -> bytes:
    return FaceRenderer(size=size).render(state)
