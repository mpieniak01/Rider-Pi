#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
common/cam_heartbeat.py — jednolity heartbeat kamery dla wszystkich previewów.
Użycie:
    from common.cam_heartbeat import CameraHB
    hb = CameraHB(mode="haar")  # albo "ssd"/"hybrid"
    ...
    hb.tick(frame, fps, presenting=True)  # wołaj co klatkę; wyśle co ~1 s
"""

import os
import time
from typing import Optional
from common.bus import BusPub, now_ts

class CameraHB:
    def __init__(self, mode: str):
        self.mode = mode
        self.pub = BusPub()
        self._last = 0.0
        try:
            self.rot = int(os.getenv("PREVIEW_ROT", "0") or 0)
        except Exception:
            self.rot = 0

    def _shape(self, frame) -> tuple[int, int]:
        try:
            h, w = frame.shape[:2]
            return int(h), int(w)
        except Exception:
            return 0, 0

    def tick(self, frame, fps: Optional[float], presenting: bool = True) -> None:
        now = time.time()
        if now - self._last < 1.0:
            return
        h, w = self._shape(frame)
        self.pub.publish(
            "camera.heartbeat",
            {
                "ts": now_ts(),  # mamy własny timestamp
                "w": w, "h": h,
                "mode": self.mode,
                "fps": float(fps) if fps is not None else None,
                "lcd": {"active": True, "presenting": bool(presenting), "rot": self.rot},
            },
            add_ts=False,
        )
        self._last = now
