from __future__ import annotations

"""
apps/draw/face_primitives.py — prymitywy rysowania buźki Rider-Pi (PIL).

Funkcje rysujące: głowa, oczy, brwi, usta, overlay (guide).
Opcje: guide (overlay), quality=fast|aa2x.
"""

import math  # noqa: E402
import os


# --- helper: pobieranie wartości z cfg (obsługuje obiekt i dict) -------------
def _cfg(cfg, name: str, default):
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


# --- resolver kształtu/otwarcia ust (priorytet: mouth.shape != "auto") -------
def _resolve_mouth(model):
    try:
        mouth = model.mouth
        shape = (getattr(mouth, "shape", "auto") or "auto").lower()
        openv = float(getattr(mouth, "open", 0.0) or 0.0)
    except Exception:
        shape, openv = "auto", 0.0

    # clamp
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
        canvas.ellipse([(cx - rx, cy - ry), (cx + rx, cy + ry)], outline=(220, 235, 255), width=2)

    # Oczy
    blink_mul = model.blink_mul() if hasattr(model, "blink_mul") else 1.0
    l = (
        cx - eye_dx - eye_w // 2,
        cy - int(eye_h * blink_mul),
        cx - eye_dx + eye_w // 2,
        cy + int(eye_h * blink_mul),
    )  # noqa: E741
    r = (
        cx + eye_dx - eye_w // 2,
        cy - int(eye_h * blink_mul),
        cx + eye_dx + eye_w // 2,
        cy + int(eye_h * blink_mul),
    )
    canvas.ellipse(l, fill=(255, 255, 255))
    canvas.ellipse(r, fill=(255, 255, 255))

    # Źrenice
    def pupil_rect(rect, off):
        x1, y1, x2, y2 = rect
        ex, ey = (x1 + x2) // 2, (y1 + y2) // 2
        pw = int(eye_w * 0.18)
        ph = int(eye_h * 0.6 * blink_mul + 2)
        return (ex - pw // 2 + off, ey - ph // 2, ex + pw // 2 + off, ey + ph // 2)

    t = 0.0  # docelowo: time.time()
    freq = 1.2 if getattr(model, "state", "idle") in ("wake", "record", "process") else 2.0
    amp = eye_w * 0.04
    phase = 0.35
    bias = int(S * 0.017)
    offL = int(math.sin(t * freq) * amp + getattr(model, "gaze_dx", 0))
    offR = int(math.sin(t * freq + phase) * amp + getattr(model, "gaze_dx", 0))
    canvas.ellipse(pupil_rect(l, +bias + offL), fill=(0, 0, 0))
    canvas.ellipse(pupil_rect(r, -bias + offR), fill=(0, 0, 0))

    # Brwi (tylko styl classic, fast)
    brow_y = cy - int(S * _cfg(cfg, "brow_y_k", 0.21))
    brow_w = int(S * 0.19)
    brow_h = int(S * _cfg(cfg, "brow_h_k", 0.09))
    stroke = max(6, int(S * 0.03))
    base_k = {"idle": 0.06, "wake": 0.10, "record": 0.08, "process": 0.04, "low_battery": 0.18}.get(
        getattr(model, "state", "idle"), 0.06
    )

    def draw_brow(ex: int, k: float):
        x0, y0 = ex - brow_w // 2, brow_y - brow_h
        x1, y1 = ex + brow_w // 2, brow_y + brow_h
        if k < 0:
            start, end = 20, 160
        else:
            start, end = 200, 340
        canvas.arc([(x0, y0), (x1, y1)], start=start, end=end, fill=(255, 255, 255), width=stroke)

    draw_brow(cx - eye_dx, base_k)
    draw_brow(cx + eye_dx, base_k)

    # Usta ---------------------------------------------------------------------

    def mouth_curvature_for(state: str) -> float:
        # historyczne „auto” z legacy – zostawione jako fallback
        k = {
            "idle": -0.48,
            "wake": -0.36,
            "record": -0.28,
            "process": -0.22,
            "low_battery": 0.25,
            "speak": -0.18,
        }.get(state, -0.24)
        if state != "low_battery" and k >= 0:
            k = -0.18 if k == 0 else -abs(k)
        if getattr(model, "expr", None) == "happy":
            k -= 0.18 * max(0.0, min(1.0, float(getattr(model, "expr_intensity", 0.0))))
        if getattr(model, "expr", None) == "neutral":
            k = -0.18
        return k

    def draw_mouth_curve(cx_i: int, y: int, w: int, k: float, width_scale: float = 1.0) -> None:
        Sloc = S
        depth = max(6, int(abs(k) * Sloc * 0.28))
        x0, y0, x1, y1 = cx_i - w // 2, y - depth, cx_i + w // 2, y + depth
        if k < 0:
            start, end = 20, 160
        else:
            start, end = 200, 340
        width_scale = _clampf(width_scale, 0.3, 3.0)
        width_px = max(8, int(Sloc * 0.055 * width_scale))
        canvas.arc([(x0, y0), (x1, y1)], start=start, end=end, fill=(0, 0, 0), width=width_px)

    # NEW: rysowanie "wstążki" (zmienna grubość + unoszenie kącików + łuk środka)
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
        """
        :param h_base: bazowa grubość w centrum (px)
        :param lift_k: ułamek S — dodatni unosi KĄCIKI (końce w górę, środek ~0)
        :param arch_k: ułamek S — dodatni opuszcza ŚRODEK (łuk w dół dla uśmiechu),
                       ujemny podnosi środek (łuk w górę dla smutku)
        :param taper_k: 0..1 – zwężenie końców
        """
        half = w / 2.0
        S_local = S
        lift_px = float(S_local) * lift_k
        arch_px = float(S_local) * arch_k
        taper_k = _clampf(float(taper_k), 0.0, 1.0)
        samples = max(16, int(samples))

        top = []
        bot = []
        # profile
        p_taper = 1.6
        p_lift = 1.8  # jak szybko rośnie efekt ku końcom (0 w środku)
        p_arch = 2.0  # jak bardzo „dociążamy” środek (max w środku, 0 na końcach)

        for i in range(samples + 1):
            x = -half + (w * i / samples)
            t = abs(x) / half  # 0 środek; 1 końce

            thickness = h_base * (1.0 - taper_k * (t**p_taper))

            # lift (kąciki): 0 w środku, max na końcach; dodatni = końce w górę
            lift = -lift_px * (t**p_lift)

            # arch (środek): max w środku, 0 na końcach; dodatni = środek w dół
            arch = arch_px * (1.0 - (t**p_arch))

            y_mid = y + lift + arch
            top.append((cx_i + x, y_mid - thickness / 2.0))
            bot.append((cx_i + x, y_mid + thickness / 2.0))

        poly = top + bot[::-1]
        canvas.polygon(poly, fill=fill)

    # Rozwiązanie shape/open z modelu (pierwszeństwo mouth.shape != "auto")
    mshape, mopen = _resolve_mouth(model)

    # Gałki ENV dla małego otwarcia (grubości)
    small_th_base = float(os.getenv("FACE_MOUTH_SMALL_TH_K_BASE", "0.050"))
    small_th_h = float(os.getenv("FACE_MOUTH_SMALL_TH_K_HAPPY", "1.00"))
    small_th_n = float(os.getenv("FACE_MOUTH_SMALL_TH_K_NEUTRAL", "0.90"))
    small_th_s = float(os.getenv("FACE_MOUTH_SMALL_TH_K_SAD", "1.05"))

    # Pozycje Y (ułamki S) – baza dla neutral/sad = 0.050
    yk_h = float(os.getenv("FACE_MOUTH_Y_OFFSET_K_HAPPY", "0.045"))
    yk_n = float(os.getenv("FACE_MOUTH_Y_OFFSET_K_NEUTRAL", "0.050"))
    yk_s = float(os.getenv("FACE_MOUTH_Y_OFFSET_K_SAD", "0.050"))

    # Profil „wstążki”
    taper_k = float(os.getenv("FACE_MOUTH_RIBBON_TAPER_K", "0.65"))
    samples = int(os.getenv("FACE_MOUTH_RIBBON_SAMPLES", "48"))

    # LIFT kącików (końce): dodatni happy, ujemny sad
    lift_h = float(os.getenv("FACE_MOUTH_HAPPY_LIFT_K", "0.040"))
    lift_n = float(os.getenv("FACE_MOUTH_NEUTRAL_LIFT_K", "0.010"))
    lift_s = float(os.getenv("FACE_MOUTH_SAD_LIFT_K", "-0.040"))

    # ARCH środka: dodatni = środek w dół (uśmiech), ujemny = środek w górę (smutek)
    arch_h = float(os.getenv("FACE_MOUTH_HAPPY_ARCH_K", "0.030"))
    arch_n = float(os.getenv("FACE_MOUTH_NEUTRAL_ARCH_K", "0.008"))
    arch_s = float(os.getenv("FACE_MOUTH_SAD_ARCH_K", "-0.030"))

    # Mowa / asysta mowy → modulowany prostokąt (legacy)
    if getattr(model, "assist_speaking", False) or getattr(model, "state", "") == "speak":
        amp_m = (
            math.sin(getattr(model, "speak_phase", 0.0))
            + math.sin(getattr(model, "speak_phase", 0.0) * 1.7) * 0.6
        )
        base_h = max(6, int(S * 0.04))
        extra_h = int(max(mopen * (S * 0.06), amp_m * (S * 0.03)))
        height = base_h + extra_h
        width = int(mouth_w * (1.0 + 0.06 * max(0.0, amp_m)))
        canvas.rectangle(
            [(cx - width // 2, mouth_y - height // 2), (cx + width // 2, mouth_y + height // 2)],
            fill=(0, 0, 0),
        )
    else:
        # --- MAŁE OTWARCIE: rysuj "wstążkę" z liftem kącików + łukiem środka ---
        if mopen < 0.08:
            if mshape == "happy":
                th = int(S * _clampf(small_th_base * small_th_h, 0.01, 0.14))
                y_draw = mouth_y + int(S * yk_h)
                _draw_ribbon_mouth(
                    cx,
                    y_draw,
                    int(mouth_w * 1.00),
                    max(1, th),
                    lift_h,
                    arch_h,
                    taper_k,
                    samples,
                    fill=(0, 0, 0),
                )
            elif mshape == "sad":
                th = int(S * _clampf(small_th_base * small_th_s, 0.01, 0.14))
                y_draw = mouth_y + int(S * yk_s)
                _draw_ribbon_mouth(
                    cx,
                    y_draw,
                    int(mouth_w * 1.00),
                    max(1, th),
                    lift_s,
                    arch_s,
                    taper_k,
                    samples,
                    fill=(0, 0, 0),
                )
            else:  # neutral
                th = int(S * _clampf(small_th_base * small_th_n, 0.01, 0.14))
                y_draw = mouth_y + int(S * yk_n)
                _draw_ribbon_mouth(
                    cx,
                    y_draw,
                    int(mouth_w * 1.00),
                    max(1, th),
                    lift_n,
                    arch_n,
                    taper_k,
                    samples,
                    fill=(0, 0, 0),
                )

        else:
            # --- WIĘKSZE OTWARCIE: pełny owal (ellipse) ----------------------
            height = max(int(S * 0.028), int(mopen * (S * 0.10)))
            width = int(mouth_w * (1.0 + 0.05 * mopen))
            canvas.ellipse(
                [
                    (cx - width // 2, mouth_y - height // 2),
                    (cx + width // 2, mouth_y + height // 2),
                ],
                fill=(0, 0, 0),
            )
