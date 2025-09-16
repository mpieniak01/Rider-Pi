
# -*- coding: utf-8 -*-
"""
apps/draw/face_primitives.py — prymitywy rysowania buźki Rider-Pi (PIL).

Funkcje rysujące: głowa, oczy, brwi, usta, overlay (guide).
Opcje: guide (overlay), quality=fast|aa2x.
"""
from PIL import Image, ImageDraw
import math

def draw_face(canvas, cfg, model, guide=True, quality="fast"):
    """
    Rysuje buźkę na podanym obiekcie ImageDraw.
    :param canvas: ImageDraw.Draw
    :param cfg: FaceConfig lub dict z parametrami geometrii
    :param model: obiekt stanu (FaceState lub podobny)
    :param guide: czy rysować overlay
    :param quality: 'fast' lub 'aa2x'
    """
    # Parametry geometryczne
    W, H = canvas.im.size
    cx, cy = W // 2, H // 2
    S = min(W, H)
    eye_dx = int(S * 0.22)
    eye_w  = int(S * 0.28)
    eye_h  = int(S * 0.12)
    mouth_w = int(S * 0.58)
    mouth_y = int(cy + S * getattr(cfg, 'mouth_y_k', 0.215))

    # Overlay (przewodnik)
    if guide:
        M = int(S * 0.04)
        rx_limit = W/2 - M; ry_limit = H/2 - M
        head_ky = getattr(cfg, 'head_ky', 1.04)
        rx = int(min(rx_limit, ry_limit / max(0.001, head_ky)))
        ry = int(min(ry_limit, rx * head_ky))
        canvas.ellipse([(cx - rx, cy - ry), (cx + rx, cy + ry)], outline=(220,235,255), width=2)

    # Oczy
    blink_mul = model.blink_mul() if hasattr(model, 'blink_mul') else 1.0
    l = (cx - eye_dx - eye_w // 2, cy - int(eye_h * blink_mul), cx - eye_dx + eye_w // 2, cy + int(eye_h * blink_mul))
    r = (cx + eye_dx - eye_w // 2, cy - int(eye_h * blink_mul), cx + eye_dx + eye_w // 2, cy + int(eye_h * blink_mul))
    canvas.ellipse(l, fill=(255,255,255))
    canvas.ellipse(r, fill=(255,255,255))

    # Źrenice
    def pupil_rect(rect, off):
        x1,y1,x2,y2 = rect
        ex, ey = (x1+x2)//2, (y1+y2)//2
        pw = int(eye_w * 0.18); ph = int(eye_h * 0.6 * blink_mul + 2)
        return (ex - pw//2 + off, ey - ph//2, ex + pw//2 + off, ey + ph//2)
    t = 0.0  # docelowo: time.time()
    freq = 1.2 if getattr(model, 'state', 'idle') in ("wake","record","process") else 2.0
    amp = eye_w * 0.04; phase = 0.35; bias = int(S * 0.017)
    offL = int(math.sin(t * freq) * amp + getattr(model, 'gaze_dx', 0))
    offR = int(math.sin(t * freq + phase) * amp + getattr(model, 'gaze_dx', 0))
    canvas.ellipse(pupil_rect(l,  +bias + offL), fill=(0,0,0))
    canvas.ellipse(pupil_rect(r,  -bias + offR), fill=(0,0,0))

    # Brwi (tylko styl classic, fast)
    brow_y = cy - int(S * getattr(cfg, 'brow_y_k', 0.21))
    brow_w = int(S * 0.19); brow_h = int(S * getattr(cfg, 'brow_h_k', 0.09))
    stroke = max(6, int(S * 0.03))
    base_k = {"idle": 0.06, "wake": 0.10, "record": 0.08, "process": 0.04, "low_battery": 0.18}.get(getattr(model, 'state', 'idle'), 0.06)
    def draw_brow(ex: int, k: float):
        x0, y0 = ex - brow_w // 2, brow_y - brow_h
        x1, y1 = ex + brow_w // 2, brow_y + brow_h
        if k < 0: start, end = 20, 160
        else:     start, end = 200, 340
        canvas.arc([(x0, y0), (x1, y1)], start=start, end=end, fill=(255,255,255), width=stroke)
    draw_brow(cx - eye_dx, base_k)
    draw_brow(cx + eye_dx, base_k)

    # Usta
    def mouth_curvature_for(state: str) -> float:
        k = {"idle": -0.48, "wake": -0.36, "record": -0.28, "process": -0.22, "low_battery": 0.25, "speak": -0.18}.get(state, -0.24)
        if state != "low_battery" and k >= 0:
            k = -0.18 if k == 0 else -abs(k)
        if getattr(model, 'expr', None) == "happy":
            k -= 0.18 * max(0.0, min(1.0, float(getattr(model, 'expr_intensity', 0.0))))
        if getattr(model, 'expr', None) == "neutral":
            k = -0.18
        return k
    def draw_mouth_curve(cx_i: int, y: int, w: int, k: float) -> None:
        Sloc = S
        depth = max(6, int(abs(k) * Sloc * 0.28))
        x0, y0, x1, y1 = cx_i - w // 2, y - depth, cx_i + w // 2, y + depth
        if k < 0: start, end = 20, 160
        else:     start, end = 200, 340
        canvas.arc([(x0, y0), (x1, y1)], start=start, end=end, fill=(0,0,0), width=max(8, int(Sloc * 0.055)))
    if getattr(model, 'assist_speaking', False) or getattr(model, 'state', '') == "speak":
        amp_m = (math.sin(getattr(model, 'speak_phase', 0.0)) + math.sin(getattr(model, 'speak_phase', 0.0)*1.7)*0.6)
        height = max(6, int(S * 0.04) + int(amp_m * (S * 0.03)))
        width  = int(mouth_w * (1.0 + 0.06 * max(0.0, amp_m)))
        canvas.rectangle([(cx - width//2, mouth_y - height//2), (cx + width//2, mouth_y + height//2)], fill=(0,0,0))
    else:
        draw_mouth_curve(cx, mouth_y, mouth_w, mouth_curvature_for(getattr(model, 'state', 'idle')))
