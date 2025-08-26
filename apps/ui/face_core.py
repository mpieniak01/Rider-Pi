#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass
from typing import Tuple, Dict, Any
import os

RGB = Tuple[int, int, int]

def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

@dataclass
class Eyes:
    dx_k: float = 0.22
    w_k:  float = 0.28
    h_k:  float = 0.12
    pupil_bias_k: float = 0.017
    sacc_amp_k:  float = 0.04

@dataclass
class Brows:
    y_k: float = 0.22
    h_k: float = 0.09
    caps: bool = True
    base_k: float = +0.06  # ∩>0, ∪<0

@dataclass
class Mouth:
    y_k: float = 0.215
    w_k: float = 0.58
    base_k: float = -0.24  # ∪<0, ∩>0

@dataclass
class Head:
    ky: float = 1.04
    guide: bool = True

@dataclass
class Palette:
    idle: RGB        = (30, 58, 138)
    wake: RGB        = (245, 158, 11)
    record: RGB      = (249, 115, 22)
    process: RGB     = (124, 58, 237)
    speak: RGB       = (16, 185, 129)
    low_battery: RGB = (239, 68, 68)

@dataclass
class FaceStyle:
    head:   Head    = Head()
    eyes:   Eyes    = Eyes()
    brows:  Brows   = Brows()
    mouth:  Mouth   = Mouth()
    colors: Palette = Palette()

def style_from_env() -> FaceStyle:
    s = FaceStyle()
    # Head
    try: s.head.ky = clamp(float(os.environ.get("FACE_HEAD_KY", s.head.ky)), 0.90, 1.20)
    except Exception: pass
    s.head.guide = bool(int(os.environ.get("FACE_GUIDE", "1")))
    # Brows
    try: s.brows.y_k = clamp(float(os.environ.get("FACE_BROW_YK", s.brows.y_k)), 0.14, 0.30)
    except Exception: pass
    try: s.brows.h_k = clamp(float(os.environ.get("FACE_BROW_HK", s.brows.h_k)), 0.06, 0.16)
    except Exception: pass
    s.brows.caps = bool(int(os.environ.get("FACE_BROW_CAPS", "1")))
    # Mouth
    try: s.mouth.y_k = clamp(float(os.environ.get("FACE_MOUTH_YK", s.mouth.y_k)), 0.18, 0.28)
    except Exception: pass
    # Eyes
    envs = {
        "FACE_EYES_DXK": ("dx_k", 0.16, 0.30),
        "FACE_EYES_WK":  ("w_k",  0.22, 0.34),
        "FACE_EYES_HK":  ("h_k",  0.08, 0.18),
    }
    for key,(attr,lo,hi) in envs.items():
        val = os.environ.get(key)
        if val:
            try: setattr(s.eyes, attr, clamp(float(val), lo, hi))
            except Exception: pass
    return s

def style_apply_config(style: FaceStyle, cfg: Dict[str, Any]) -> None:
    if "head_ky" in cfg:
        try: style.head.ky = clamp(float(cfg["head_ky"]), 0.90, 1.20)
        except Exception: pass
    if "guide" in cfg:
        try: style.head.guide = bool(int(cfg["guide"]))
        except Exception: style.head.guide = bool(cfg["guide"])
    if "brow_y_k" in cfg:
        try: style.brows.y_k = clamp(float(cfg["brow_y_k"]), 0.14, 0.30)
        except Exception: pass
    if "brow_h_k" in cfg:
        try: style.brows.h_k = clamp(float(cfg["brow_h_k"]), 0.06, 0.16)
        except Exception: pass
    if "brow_caps" in cfg:
        try: style.brows.caps = bool(int(cfg["brow_caps"]))
        except Exception: style.brows.caps = bool(cfg["brow_caps"])
    if "mouth_y_k" in cfg:
        try: style.mouth.y_k = clamp(float(cfg["mouth_y_k"]), 0.18, 0.28)
        except Exception: pass
    eyes = cfg.get("eyes")
    if isinstance(eyes, dict):
        if "dx_k" in eyes:
            try: style.eyes.dx_k = clamp(float(eyes["dx_k"]), 0.16, 0.30)
            except Exception: pass
        if "w_k" in eyes:
            try: style.eyes.w_k  = clamp(float(eyes["w_k"]),  0.22, 0.34)
            except Exception: pass
        if "h_k" in eyes:
            try: style.eyes.h_k  = clamp(float(eyes["h_k"]),  0.08, 0.18)
            except Exception: pass
