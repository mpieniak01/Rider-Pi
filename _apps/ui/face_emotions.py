#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class ExprAdjust:
    bg_state: str = "idle"
    brow_k: float = 0.0
    mouth_k: float = 0.0
    mouth_w_add: float = 0.0
    blink_now: bool = False

EXPR_MAP = {
  "neutral":     ExprAdjust(bg_state="idle",  brow_k=+0.06, mouth_k=-0.18),
  "happy":       ExprAdjust(bg_state="idle",  brow_k=+0.10, mouth_k=-0.24, mouth_w_add=0.02),
  "wake":        ExprAdjust(bg_state="wake",  brow_k=+0.10, mouth_k=-0.36, blink_now=True),
  "record":      ExprAdjust(bg_state="record",brow_k=+0.08, mouth_k=-0.28),
  "process":     ExprAdjust(bg_state="process",brow_k=+0.04, mouth_k=-0.22),
  "speak":       ExprAdjust(bg_state="speak", mouth_k=-0.18),
  "low_battery": ExprAdjust(bg_state="low_battery", brow_k=+0.18, mouth_k=+0.25),
}
