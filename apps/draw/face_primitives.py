from __future__ import annotations

import math
import os
import time

# apps/draw/face_primitives.py — prymitywy rysowania buźki Rider-Pi (PIL).
# Funkcje rysujące: głowa, oczy, brwi, usta, overlay (guide).
# Opcje: guide (overlay), quality=fast|aa2x.
#
# UWAGA:
#  • Brwi i usta = wersja referencyjna (łuki arc + „wstążka”).
#  • Źrenice: realny czas, mikrodryf, clamp, respekt `eyes.dx/dy`.
#  • Pokrętła wytłumienia ruchu (cfg lub ENV):
#     - eyes_follow_kx / eyes_follow_ky – ile całe oko podąża za look
#     - brow_follow_kx / brow_follow_ky – ile brwi podążają za okiem


def _cfg(cfg, name: str, default):
    """Pobierz wartość z cfg (obsługuje obiekt i dict)."""
    try:
        if hasattr(cfg, name):
            return getattr(cfg, name)
        if isinstance(cfg, dict):
            return cfg.get(name, default)
    except Exception:
        pass
    return default


def _clampf(x: float, lo: float, hi: float) -> float:
    return hi if x > hi else lo if x < lo else x


def _resolve_mouth(model) -> tuple[str, float]:
    """Resolver kształtu/otwarcia ust (priorytet: mouth.shape != 'auto')."""
    try:
        mouth = model.mouth
        shape = (getattr(mouth, "shape", "auto") or "auto").lower()
        openv = float(getattr(mouth, "open", 0.0) or 0.0)
    except Exception:
        shape, openv = "auto", 0.0

    if openv < 0.0:
        openv = 0.0
    if openv > 1.0:
        openv = 1.0

    if shape == "auto":
        expr = getattr(model, "expr", "neutral")
        shape = {"happy": "happy", "sad": "sad"}.get(expr, "neutral")

    return shape, openv


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
    eye_w = int(S * 0.28)
    eye_h = int(S * 0.12)
    mouth_w = int(S * 0.58)
    mouth_y = int(cy + S * _cfg(cfg, "mouth_y_k", 0.215))

    # Overlay (przewodnik)
    if guide:
        M = int(S * 0.04)
        rx_limit = W / 2 - M
        ry_limit = H / 2 - M
        head_ky = _cfg(cfg, "head_ky", 1.04)
        rx = int(min(rx_limit, ry_limit / max(0.001, head_ky)))
        ry = int(min(ry_limit, rx * head_ky))
        canvas.ellipse(
            [(cx - rx, cy - ry), (cx + rx, cy + ry)],
            outline=(220, 235, 255),
            width=2,
        )

    # Oczy (białko)
    blink_mul = model.blink_mul() if hasattr(model, "blink_mul") else 1.0

    # ruchem całego oka (białka) steruje look + pokrętła follow
    eyes_dx = 0.0
    eyes_dy = 0.0
    try:
        eyes = getattr(model, "eyes", None)
        if eyes is not None:
            eyes_dx = float(getattr(eyes, "dx", 0.0) or 0.0)
            eyes_dy = float(getattr(eyes, "dy", 0.0) or 0.0)
    except Exception:
        pass

    eyes_follow_kx = float(os.getenv("FACE_EYES_FOLLOW_KX", str(_cfg(cfg, "eyes_follow_kx", 0.18))))
    eyes_follow_ky = float(os.getenv("FACE_EYES_FOLLOW_KY", str(_cfg(cfg, "eyes_follow_ky", 0.30))))

    eye_cx_offset = int(eyes_dx * eye_w * eyes_follow_kx)
    eye_cy_offset = int(eyes_dy * eye_h * eyes_follow_ky)

    left_eye_rect = (
        cx - eye_dx - eye_w // 2 + eye_cx_offset,
        cy - int(eye_h * blink_mul) + eye_cy_offset,
        cx - eye_dx + eye_w // 2 + eye_cx_offset,
        cy + int(eye_h * blink_mul) + eye_cy_offset,
    )
    right_eye_rect = (
        cx + eye_dx - eye_w // 2 + eye_cx_offset,
        cy - int(eye_h * blink_mul) + eye_cy_offset,
        cx + eye_dx + eye_w // 2 + eye_cx_offset,
        cy + int(eye_h * blink_mul) + eye_cy_offset,
    )
    canvas.ellipse(left_eye_rect, fill=(255, 255, 255))
    canvas.ellipse(right_eye_rect, fill=(255, 255, 255))

    # Źrenice (drift/clamp/look)
    def pupil_rect(rect, off_x, off_y):
        x1, y1, x2, y2 = rect
        ex, ey = (x1 + x2) // 2, (y1 + y2) // 2
        pw = int(eye_w * 0.18)
        ph = int(eye_h * 0.6 * blink_mul + 2)
        return (
            ex - pw // 2 + off_x,
            ey - ph // 2 + off_y,
            ex + pw // 2 + off_x,
            ey + ph // 2 + off_y,
        )

    t = time.time()
    drift_freq = float(os.getenv("FACE_PUPIL_DRIFT_FREQ", "0.8"))
    drift_amp_k = float(os.getenv("FACE_PUPIL_DRIFT_AMP_K", "0.04"))
    amp_px = eye_w * max(0.0, drift_amp_k)
    phase = 0.35
    drift_scale = 1.0 if blink_mul >= 0.6 else (blink_mul / 0.6)

    driftL_x = int(math.sin(t * drift_freq) * amp_px * drift_scale)
    driftR_x = int(math.sin(t * drift_freq + phase) * amp_px * drift_scale)
    v_amp_px = amp_px * 0.5
    driftL_y = int(math.cos(t * (drift_freq * 0.8)) * v_amp_px * drift_scale)
    driftR_y = int(math.cos(t * (drift_freq * 0.8) + phase) * v_amp_px * drift_scale)

    bias = int(S * 0.017)
    base_dx = int(eyes_dx * eye_w * 0.30)  # przesunięcie źrenicy wzgl. oka
    base_dy = int(eyes_dy * eye_h * 0.45)
    offL_x = +bias + base_dx + driftL_x
    offR_x = -bias + base_dx + driftR_x
    offL_y = base_dy + driftL_y
    offR_y = base_dy + driftR_y

    clamp_ratio = float(os.getenv("FACE_PUPIL_CLAMP_RATIO", "0.78"))
    max_x = int(eye_w * 0.5 - eye_w * (1.0 - clamp_ratio) * 0.5)
    max_y = int(eye_h * blink_mul * 0.9)

    def _clamp_off(off_x, off_y):
        return (
            max(-max_x, min(max_x, off_x)),
            max(-max_y, min(max_y, off_y)),
        )

    offL_x, offL_y = _clamp_off(offL_x, offL_y)
    offR_x, offR_y = _clamp_off(offR_x, offR_y)

    canvas.ellipse(pupil_rect(left_eye_rect, offL_x, offL_y), fill=(0, 0, 0))
    canvas.ellipse(pupil_rect(right_eye_rect, offR_x, offR_y), fill=(0, 0, 0))

    # Brwi – łuki „arc”; podążanie za okiem można wyciszyć
    brow_y = cy - int(S * _cfg(cfg, "brow_y_k", 0.21))
    brow_w = int(S * 0.19)
    brow_h = int(S * _cfg(cfg, "brow_h_k", 0.09))
    stroke = max(6, int(S * 0.03))
    base_k = {
        "idle": 0.06,
        "wake": 0.10,
        "record": 0.08,
        "process": 0.04,
        "low_battery": 0.18,
    }.get(getattr(model, "state", "idle"), 0.06)

    brow_follow_kx = float(os.getenv("FACE_BROW_FOLLOW_KX", str(_cfg(cfg, "brow_follow_kx", 0.10))))
    brow_follow_ky = float(os.getenv("FACE_BROW_FOLLOW_KY", str(_cfg(cfg, "brow_follow_ky", 0.20))))
    brow_off_x = int(eyes_dx * eye_w * brow_follow_kx)
    brow_off_y = int(eyes_dy * eye_h * brow_follow_ky)

    def draw_brow(ex: int, k: float):
        x0 = ex - brow_w // 2 + brow_off_x
        y0 = brow_y - brow_h + brow_off_y
        x1 = ex + brow_w // 2 + brow_off_x
        y1 = brow_y + brow_h + brow_off_y
        start, end = (20, 160) if k < 0 else (200, 340)
        canvas.arc(
            [(x0, y0), (x1, y1)],
            start=start,
            end=end,
            fill=(255, 255, 255),
            width=stroke,
        )

    draw_brow(cx - eye_dx, base_k)
    draw_brow(cx + eye_dx, base_k)

    # Usta — „wstążka”
    def _draw_ribbon_mouth(
        cx_i: int,
        y: int,
        w: int,
        h_base: int,
        lift_k: float,
        arch_k: float,
        taper_k: float,
        samples: int,
        fill=(0, 0, 0),
    ) -> None:
        half = w / 2.0
        S_local = S
        lift_px = float(S_local) * lift_k
        arch_px = float(S_local) * arch_k
        taper_k = _clampf(float(taper_k), 0.0, 1.0)
        samples = max(16, int(samples))

        top = []
        bot = []
        p_taper = 1.6
        p_lift = 1.8
        p_arch = 2.0

        for i in range(samples + 1):
            x = -half + (w * i / samples)
            t = abs(x) / half  # 0 środek; 1 końce

            thickness = h_base * (1.0 - taper_k * (t**p_taper))
            lift = -lift_px * (t**p_lift)
            arch = arch_px * (1.0 - (t**p_arch))

            y_mid = y + lift + arch
            top.append((cx_i + x, y_mid - thickness / 2.0))
            bot.append((cx_i + x, y_mid + thickness / 2.0))

        poly = top + bot[::-1]
        canvas.polygon(poly, fill=fill)

    mshape, mopen = _resolve_mouth(model)

    small_th_base = float(os.getenv("FACE_MOUTH_SMALL_TH_K_BASE", "0.050"))
    small_th_h = float(os.getenv("FACE_MOUTH_SMALL_TH_K_HAPPY", "1.00"))
    small_th_n = float(os.getenv("FACE_MOUTH_SMALL_TH_K_NEUTRAL", "0.90"))
    small_th_s = float(os.getenv("FACE_MOUTH_SMALL_TH_K_SAD", "1.05"))

    yk_h = float(os.getenv("FACE_MOUTH_Y_OFFSET_K_HAPPY", "0.045"))
    yk_n = float(os.getenv("FACE_MOUTH_Y_OFFSET_K_NEUTRAL", "0.050"))
    yk_s = float(os.getenv("FACE_MOUTH_Y_OFFSET_K_SAD", "0.050"))

    taper_k = float(os.getenv("FACE_MOUTH_RIBBON_TAPER_K", "0.60"))
    samples = int(os.getenv("FACE_MOUTH_RIBBON_SAMPLES", "48"))

    lift_h = float(os.getenv("FACE_MOUTH_HAPPY_LIFT_K", "0.045"))
    lift_n = float(os.getenv("FACE_MOUTH_NEUTRAL_LIFT_K", "0.000"))
    lift_s = float(os.getenv("FACE_MOUTH_SAD_LIFT_K", "-0.045"))

    arch_h = float(os.getenv("FACE_MOUTH_HAPPY_ARCH_K", "0.030"))
    arch_n = float(os.getenv("FACE_MOUTH_NEUTRAL_ARCH_K", "0.000"))
    arch_s = float(os.getenv("FACE_MOUTH_SAD_ARCH_K", "-0.030"))

    if getattr(model, "assist_speaking", False) or getattr(model, "state", "") == "speak":
        amp_m = math.sin(getattr(model, "speak_phase", 0.0)) + math.sin(getattr(model, "speak_phase", 0.0) * 1.7) * 0.6
        base_h = max(6, int(S * 0.04))
        extra_h = int(max(mopen * (S * 0.06), amp_m * (S * 0.03)))
        height = base_h + extra_h
        width = int(mouth_w * (1.0 + 0.06 * max(0.0, amp_m)))
        canvas.rectangle(
            [
                (cx - width // 2, mouth_y - height // 2),
                (cx + width // 2, mouth_y + height // 2),
            ],
            fill=(0, 0, 0),
        )
    else:
        if mopen < 0.08:
            if mshape == "happy":
                th = int(S * _clampf(small_th_base * small_th_h, 0.01, 0.14))
                y_draw = mouth_y + int(S * yk_h)
                _draw_ribbon_mouth(cx, y_draw, int(mouth_w * 1.00), max(1, th), lift_h, arch_h, taper_k, samples)
            elif mshape == "sad":
                th = int(S * _clampf(small_th_base * small_th_s, 0.01, 0.14))
                y_draw = mouth_y + int(S * yk_s)
                _draw_ribbon_mouth(cx, y_draw, int(mouth_w * 1.00), max(1, th), lift_s, arch_s, taper_k, samples)
            else:
                th = int(S * _clampf(small_th_base * small_th_n, 0.01, 0.14))
                y_draw = mouth_y + int(S * yk_n)
                _draw_ribbon_mouth(cx, y_draw, int(mouth_w * 1.00), max(1, th), lift_n, arch_n, taper_k, samples)
        else:
            height = max(int(S * 0.028), int(mopen * (S * 0.10)))
            width = int(mouth_w * (1.0 + 0.05 * mopen))
            canvas.ellipse(
                [
                    (cx - width // 2, mouth_y - height // 2),
                    (cx + width // 2, mouth_y + height // 2),
                ],
                fill=(0, 0, 0),
            )
