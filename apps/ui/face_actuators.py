#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass
from typing import Tuple, Optional
import math, time

from .face_core import FaceStyle, clamp
from .face_emotions import ExprAdjust, EXPR_MAP

Rect = Tuple[int,int,int,int]
Arc  = Tuple[Rect, int, int, int]  # (bbox, start_deg, end_deg, stroke_px)

@dataclass
class FaceFrame:
    bg_rgb: Tuple[int,int,int]
    guide: bool
    brow_caps: bool
    head_bbox: Optional[Rect]
    eye_l: Rect; eye_r: Rect
    pupil_l: Rect; pupil_r: Rect
    brow_l: Arc;  brow_r: Arc
    mouth_arc: Optional[Arc] = None
    mouth_rect: Optional[Rect] = None

def compute_frame(style: FaceStyle,
                  expr: Optional[str],
                  intensity: float,
                  state: str,
                  speaking: bool,
                  blink_mul: float,
                  sacc_dx: float,
                  cw: int, ch: int,
                  speak_phase: float,
                  t: float = None) -> FaceFrame:
    if t is None: t = time.time()

    cx, cy = cw // 2, ch // 2
    S = min(cw, ch)

    # emocja → delty
    adj: ExprAdjust = EXPR_MAP.get(expr or "neutral", EXPR_MAP["neutral"])
    k = clamp(float(intensity), 0.0, 1.0)

    # tło
    bg_state = adj.bg_state or state
    bg_rgb = getattr(style.colors, bg_state, style.colors.idle)

    # głowa (przewodnik)
    M = int(S * 0.04)
    rx_limit = cw/2 - M
    ry_limit = ch/2 - M
    rx = int(min(rx_limit, ry_limit / max(0.001, style.head.ky)))
    ry = int(min(ry_limit, rx * style.head.ky))
    head_bbox = (cx - rx, cy - ry, cx + rx, cy + ry)

    # oczy
    eye_dx = int(S * style.eyes.dx_k)
    eye_w  = int(S * style.eyes.w_k)
    eye_h0 = int(S * style.eyes.h_k)
    eye_h  = int(eye_h0 * blink_mul)
    eye_l = (cx - eye_dx - eye_w//2, cy - eye_h, cx - eye_dx + eye_w//2, cy + eye_h)
    eye_r = (cx + eye_dx - eye_w//2, cy - eye_h, cx + eye_dx + eye_w//2, cy + eye_h)

    # źrenice
    freq  = 1.2 if state in ("wake","record","process") else 2.0
    amp   = int(eye_w * style.eyes.sacc_amp_k)
    phase = 0.35
    bias  = int(S * style.eyes.pupil_bias_k)
    offL = int(math.sin(t * freq) * amp + sacc_dx)
    offR = int(math.sin(t * freq + phase) * amp + sacc_dx)
    def pup(rect, xoff):
        x1, y1, x2, y2 = rect
        ex, ey = (x1+x2)//2, (y1+y2)//2
        pw = int(eye_w * 0.18)
        ph = int(eye_h0 * 0.60 * blink_mul + 2)
        return (ex - pw//2 + xoff, ey - ph//2, ex + pw//2 + xoff, ey + ph//2)
    pupil_l = pup(eye_l, +bias + offL)
    pupil_r = pup(eye_r, -bias + offR)

    # brwi
    brow_y = cy - int(S * style.brows.y_k)
    brow_w = int(S * 0.19)
    brow_h = int(S * style.brows.h_k)
    stroke = max(6, int(S * 0.03))
    # stan → lekki bias (∩ dodatni)
    state_brow = {"idle": +0.06, "wake": +0.10, "record": +0.08, "process": +0.04, "low_battery": +0.18}.get(state, +0.06)
    k_brow = state_brow + adj.brow_k * k
    def brow_arc(ex: int, k: float) -> Arc:
        x0, y0 = ex - brow_w//2, brow_y - brow_h
        x1, y1 = ex + brow_w//2, brow_y + brow_h
        if k < 0: start, end = 20, 160   # ∪
        else:     start, end = 200, 340  # ∩
        return ((x0, y0, x1, y1), start, end, stroke)
    brow_l = brow_arc(cx - eye_dx, k_brow)
    brow_r = brow_arc(cx + eye_dx, k_brow)

    # usta
    mouth_w = int(S * style.mouth.w_k * (1.0 + adj.mouth_w_add * k))
    mouth_y = cy + int(S * style.mouth.y_k)
    if speaking or state == "speak":
        amp_m = (math.sin(speak_phase) + math.sin(speak_phase*1.7)*0.6)
        height = max(6, int(S * 0.04) + int(amp_m * (S * 0.03)))
        width  = int(mouth_w * (1.0 + 0.06 * max(0.0, amp_m)))
        mouth_rect = (cx - width//2, mouth_y - height//2, cx + width//2, mouth_y + height//2)
        return FaceFrame(bg_rgb, style.head.guide, style.brows.caps, head_bbox,
                         eye_l, eye_r, pupil_l, pupil_r, brow_l, brow_r,
                         mouth_arc=None, mouth_rect=mouth_rect)
    else:
        # stan → bazowy uśmiech/smutek (∪ ujemny)
        state_mouth = {"idle": -0.48, "wake": -0.36, "record": -0.28, "process": -0.22, "low_battery": +0.25, "speak": -0.18}.get(state, -0.24)
        k_mouth = style.mouth.base_k + state_mouth + adj.mouth_k * k
        depth = max(6, int(abs(k_mouth) * S * 0.28))
        x0, y0, x1, y1 = cx - mouth_w//2, mouth_y - depth, cx + mouth_w//2, mouth_y + depth
        if k_mouth < 0: start, end = 20, 160   # ∪ (uśmiech)
        else:           start, end = 200, 340  # ∩ (smutek)
        mouth_arc = ((x0, y0, x1, y1), start, end, max(8, int(S * 0.055)))
        return FaceFrame(bg_rgb, style.head.guide, style.brows.caps, head_bbox,
                         eye_l, eye_r, pupil_l, pupil_r, brow_l, brow_r,
                         mouth_arc=mouth_arc, mouth_rect=None)
