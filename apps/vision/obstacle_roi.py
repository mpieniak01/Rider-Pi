#!/usr/bin/env python3
"""
Rider-Pi: obstacle detector based on edge density in a bottom ROI.

We read the processed edge frame (PROC_PATH), compute edge density within a
configurable ROI, and write obstacle.json atomically. Adds freshness info
(age_s, stale) and simple debounce to smooth decisions.

ENV (defaults aligned with systemd unit):
- PROC_PATH=/home/pi/robot/snapshots/proc.jpg
- DATA_DIR=/home/pi/robot/data
- OBSTACLE_JSON=/home/pi/robot/data/obstacle.json
- ROI_Y0=0.55        # fraction from top (0..1)
- ROI_H=0.40         # ROI height fraction (0..1), clamped to frame
- EDGE_AREA_PCT=0.18 # fraction (0..1) of non-zero edge pixels to trigger
- EDGE_PIX_MIN=16000 # absolute pixel count threshold
- SNAP_MAX_AGE_S=3.0 # mark data as stale if proc.jpg older than this
- OBST_DEC_N=3       # debounce window length (samples)
- PUBLISH=0/1        # optional: publish to ZMQ bus if available
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

import cv2  # type: ignore
import numpy as np

# --------------------------- config helpers ---------------------------------


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


PROC_PATH = os.getenv("PROC_PATH", "/home/pi/robot/snapshots/proc.jpg")
DATA_DIR = os.getenv("DATA_DIR", "/home/pi/robot/data")
OBSTACLE_JSON = os.getenv("OBSTACLE_JSON", f"{DATA_DIR}/obstacle.json")

ROI_Y0 = _env_float("ROI_Y0", 0.55)
ROI_H = _env_float("ROI_H", 0.40)

EDGE_AREA_PCT = _env_float("EDGE_AREA_PCT", 0.18)
EDGE_PIX_MIN = _env_int("EDGE_PIX_MIN", 16000)

SNAP_MAX_AGE_S = _env_float("SNAP_MAX_AGE_S", 3.0)
OBST_DEC_N = _env_int("OBST_DEC_N", 3)

PUBLISH = _env_int("PUBLISH", 0)

# ----------------------------- utils ----------------------------------------


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def now_s() -> float:
    return time.time()


def atomic_write_json(path: str, obj: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    os.replace(tmp, p)


def proc_mtime_age(path: str) -> tuple[float, float]:
    try:
        mtime = Path(path).stat().st_mtime
    except FileNotFoundError:
        return 0.0, float("inf")
    t = now_s()
    return mtime, max(0.0, t - mtime)


def load_proc_gray(path: str) -> np.ndarray | None:
    # PROC jest już obrazem krawędzi (binarne/dużo czerni) – czytamy w gray.
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    return img


def roi_slice(h: int, y0_frac: float, h_frac: float) -> slice:
    y0_frac = clamp(y0_frac, 0.0, 1.0)
    h_frac = clamp(h_frac, 0.0, 1.0)
    y0 = int(round(h * y0_frac))
    y1 = int(round(h * clamp(y0_frac + h_frac, 0.0, 1.0)))
    if y1 <= y0:
        y1 = min(h, y0 + 1)
    return slice(y0, y1)


def edge_stats(gray: np.ndarray, sl: slice) -> tuple[int, int, float]:
    """
    Zwraca: (edge_nz, roi_px, edge_pct)
    Liczymy piksele != 0 (PROC to obraz krawędzi).
    """
    roi = gray[sl, :]
    nz = cv2.countNonZero(roi)
    total = int(roi.shape[0] * roi.shape[1])
    pct = (nz / total) if total > 0 else 0.0
    return nz, total, pct


def decide(edge_pct: float, edge_nz: int) -> bool:
    return (edge_pct >= EDGE_AREA_PCT) or (edge_nz >= EDGE_PIX_MIN)


# ----------------------------- optional bus ---------------------------------

_bus = None
if PUBLISH:
    try:
        import zmq  # type: ignore

        _ctx = zmq.Context.instance()
        _bus = _ctx.socket(zmq.PUB)
        # domyślny endpoint – dopasuj do swojego brokera jeśli inny
        _bus.bind("tcp://127.0.0.1:5557")
    except Exception:
        _bus = None


def publish(topic: str, payload: dict[str, Any]) -> None:
    if not _bus:
        return
    try:
        _bus.send_multipart([topic.encode("utf-8"), json.dumps(payload).encode("utf-8")])
    except Exception:
        pass


# ------------------------------- main loop ----------------------------------

_STOP = False


def _sigint(_a, _b):
    global _STOP
    _STOP = True
    print("[obst] stop", flush=True)


def main() -> int:
    signal.signal(signal.SIGINT, _sigint)
    signal.signal(signal.SIGTERM, _sigint)

    hist = deque(maxlen=max(1, OBST_DEC_N))

    print(
        f"[obst] start PROC={PROC_PATH} ROI={ROI_Y0:.2f}+{ROI_H:.2f} "
        f"TH={EDGE_AREA_PCT:.3f}/{EDGE_PIX_MIN} DEC_N={OBST_DEC_N}",
        flush=True,
    )

    while not _STOP:
        mtime, age_s = proc_mtime_age(PROC_PATH)
        img = load_proc_gray(PROC_PATH)

        if img is None:
            payload = {
                "type": "obstacle",
                "present": False,
                "confidence": 0.0,
                "edge_pct": 0.0,
                "edge_nz": 0,
                "roi": {"y0": 0, "y1": 0, "w": 0, "h": 0},
                "ts": now_s(),
                "age_s": age_s,
                "stale": age_s > SNAP_MAX_AGE_S,
                "error": "proc_not_found",
            }
            atomic_write_json(OBSTACLE_JSON, payload)
            publish("vision.obstacle", payload)
            time.sleep(0.25)
            continue

        h, w = img.shape[:2]
        sl = roi_slice(h, ROI_Y0, ROI_H)
        y0, y1 = sl.start, sl.stop

        edge_nz, roi_px, edge_pct = edge_stats(img, sl)
        curr_present = decide(edge_pct, edge_nz)

        hist.append(1 if curr_present else 0)
        # Debounce: present=True dopiero, gdy wszystkie ostatnie N są True.
        present = sum(hist) == len(hist)
        # Confidence: odległość od progu w prostym ujęciu (0..1)
        # liczona na bazie edge_pct (ma lepszą stabilność niż nz).
        margin = max(1e-6, max(edge_pct, EDGE_AREA_PCT))
        conf = clamp((edge_pct - EDGE_AREA_PCT) / margin + (1 if present else 0) * 0.0, 0.0, 1.0)

        payload = {
            "type": "obstacle",
            "present": bool(present),
            "confidence": round(conf, 3),
            "edge_pct": round(edge_pct, 4),
            "edge_nz": int(edge_nz),
            "roi": {"y0": int(y0), "y1": int(y1), "w": int(w), "h": int(h)},
            "ts": now_s(),
            "age_s": round(age_s, 3),
            "stale": bool(age_s > SNAP_MAX_AGE_S),
        }

        atomic_write_json(OBSTACLE_JSON, payload)
        publish("vision.obstacle", payload)

        print(
            f"[obst] snap present={payload['present']} pct={payload['edge_pct']:.3f} "
            f"nz={edge_nz} roi=({y0}:{y1}/{h})",
            flush=True,
        )

        # ~10 Hz przy szybkim pipeline, ale ramki i tak powstają ~10–20/s
        time.sleep(0.1)

    return 0


if __name__ == "__main__":
    sys.exit(main())
