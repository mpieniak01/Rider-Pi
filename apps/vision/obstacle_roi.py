#!/usr/bin/env python3
"""
Rider-Pi: obstacle detector based on edge *scarcity* in a bottom ROI.

Zmiany vs poprzednia wersja:
- MAŁO krawędzi ⇒ przeszkoda (present=True), histereza EDGE_T_LOW/HIGH.
- Bezpieczniki: DARK_LUMA (ciemno) i LAPL_VAR_MIN (rozmycie) ⇒ przeszkoda.
- Confidence liczone zgodnie z nową semantyką.
- (NOWE) Opcjonalne annotacje obrazu na PROC: kolorowy ROI + status + słabe-kolumny.
"""

from __future__ import annotations

import json
import signal
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

import cv2  # type: ignore
import numpy as np

from apps.vision.ai_mode_adapter import log_vision_mode_status, should_run_local_detectors
from apps.vision.config import load_config
from common.bus import TOPIC_SYSTEM_AI_MODE_CHANGED, BusSub

# --------------------------- config helpers ---------------------------------

# Load configuration (TOML > ENV > defaults)
_cfg = load_config()
_obst_cfg = _cfg.obstacle

PROC_PATH = _obst_cfg.proc_path
RAW_PATH = _obst_cfg.raw_path
DATA_DIR = _obst_cfg.data_dir
OBSTACLE_JSON = _obst_cfg.obstacle_json

ROI_Y0 = _obst_cfg.roi_y0
ROI_H = _obst_cfg.roi_h

# Legacy (diag)
EDGE_AREA_PCT = _obst_cfg.edge_area_pct
EDGE_PIX_MIN = _obst_cfg.edge_pix_min

# Histereza
EDGE_T_LOW = _obst_cfg.edge_t_low
EDGE_T_HIGH = _obst_cfg.edge_t_high

# Bezpieczniki
DARK_LUMA = _obst_cfg.dark_luma
LAPL_VAR_MIN = _obst_cfg.lapl_var_min

CONF_GAIN = _obst_cfg.conf_gain

SNAP_MAX_AGE_S = _obst_cfg.snap_max_age_s
OBST_DEC_N = _obst_cfg.obst_dec_n

PUBLISH = _obst_cfg.publish

# Annotacje
OBST_ANN = _obst_cfg.obst_ann
OBST_ANN_PATH = _obst_cfg.obst_ann_path
OBST_BINS = _obst_cfg.obst_bins
EDGE_BIN_LOW = _obst_cfg.edge_bin_low

# sanity
if EDGE_T_LOW > EDGE_T_HIGH:
    EDGE_T_LOW, EDGE_T_HIGH = EDGE_T_HIGH, EDGE_T_LOW


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
    tmp.replace(p)


def file_mtime_age(path: str) -> tuple[float, float]:
    try:
        mtime = Path(path).stat().st_mtime
    except FileNotFoundError:
        return 0.0, float("inf")
    t = now_s()
    return mtime, max(0.0, t - mtime)


def load_gray(path: str) -> np.ndarray | None:
    return cv2.imread(path, cv2.IMREAD_GRAYSCALE)


def roi_slice(h: int, y0_frac: float, h_frac: float) -> slice:
    y0_frac = clamp(y0_frac, 0.0, 1.0)
    h_frac = clamp(h_frac, 0.0, 1.0)
    y0 = int(round(h * y0_frac))
    y1 = int(round(h * clamp(y0_frac + h_frac, 0.0, 1.0)))
    if y1 <= y0:
        y1 = min(h, y0 + 1)
    return slice(y0, y1)


def edge_stats(edge_gray: np.ndarray, sl: slice) -> tuple[int, int, float]:
    roi = edge_gray[sl, :]
    nz = cv2.countNonZero(roi)
    total = int(roi.shape[0] * roi.shape[1])
    pct = (nz / total) if total > 0 else 0.0
    return nz, total, pct


def luma_and_focus(gray_raw: np.ndarray, sl: slice) -> tuple[float, float]:
    roi = gray_raw[sl, :]
    mean_luma = float(np.mean(roi)) / 255.0 if roi.size else 0.0
    lap = cv2.Laplacian(roi, cv2.CV_64F)
    lap_var = float(lap.var()) if roi.size else 0.0
    return mean_luma, lap_var


def median_of(deq: deque[float]) -> float:
    arr = sorted(deq)
    n = len(arr)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return arr[mid]
    return 0.5 * (arr[mid - 1] + arr[mid])


# ----------------------------- annotations ----------------------------------


def _to_bgr(img_gray: np.ndarray) -> np.ndarray:
    if len(img_gray.shape) == 2:
        return cv2.cvtColor(img_gray, cv2.COLOR_GRAY2BGR)
    return img_gray.copy()


def bins_edge_pcts(edge_gray: np.ndarray, sl: slice, bins: int) -> list[float]:
    roi = edge_gray[sl, :]
    h, w = roi.shape[:2]
    bins = max(1, int(bins))
    bin_w = max(1, w // bins)
    out: list[float] = []
    for i in range(bins):
        x0 = i * bin_w
        x1 = w if i == bins - 1 else min(w, (i + 1) * bin_w)
        col = roi[:, x0:x1]
        nz = cv2.countNonZero(col)
        total = int(col.shape[0] * col.shape[1])
        out.append((nz / total) if total > 0 else 0.0)
    return out


def draw_overlay(
    base_gray: np.ndarray,
    sl: slice,
    present: bool,
    confidence: float,
    edge_pct: float,
    bins_pcts: list[float] | None,
    ann_path: str,
) -> None:
    try:
        vis = _to_bgr(base_gray)
        h, w = vis.shape[:2]
        y0, y1 = sl.start, sl.stop

        color = (0, 200, 0) if not present else (0, 0, 220)
        overlay = vis.copy()
        cv2.rectangle(overlay, (0, y0), (w - 1, y1 - 1), color, thickness=-1)
        cv2.addWeighted(overlay, 0.15, vis, 0.85, 0, vis)

        cv2.line(vis, (0, y0), (w - 1, y0), (180, 180, 0), 1)
        cv2.line(vis, (0, y1), (w - 1, y1), (180, 180, 0), 1)

        if bins_pcts:
            bin_w = max(1, w // max(1, len(bins_pcts)))
            for i, p in enumerate(bins_pcts):
                if p < EDGE_BIN_LOW:
                    x0 = i * bin_w
                    x1 = min(w - 1, (i + 1) * bin_w - 1)
                    cv2.rectangle(vis, (x0, y0), (x1, y1 - 1), (0, 0, 255), 1)

        txt = f"present={present} conf={confidence:.2f} edge={edge_pct:.3f}"
        cv2.putText(
            vis,
            txt,
            (8, max(16, y0 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

        cv2.imwrite(ann_path, vis, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    except Exception as e:
        print("[obst][annot] ERROR:", e, flush=True)


# ----------------------------- optional bus ---------------------------------

_bus = None
if PUBLISH:
    try:
        import zmq  # type: ignore

        _ctx = zmq.Context.instance()
        _bus = _ctx.socket(zmq.PUB)
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

    # Log AI mode status at startup
    log_vision_mode_status()

    # Subscribe to AI mode change events
    sub_ai_mode = None
    try:
        sub_ai_mode = BusSub(TOPIC_SYSTEM_AI_MODE_CHANGED)
    except Exception as e:
        print(f"[obst] WARNING: Could not subscribe to AI mode changes: {e}", flush=True)

    # Initial mode check
    detector_active = should_run_local_detectors()
    if not detector_active:
        print("[obst] AI Mode: pc_offload - local detector paused, waiting for mode change", flush=True)
    else:
        print("[obst] AI Mode: local - running local detector", flush=True)

    edge_hist = deque(maxlen=max(1, OBST_DEC_N))
    last_present = False

    print(
        (
            f"[obst] start PROC={PROC_PATH} RAW={RAW_PATH} ROI={ROI_Y0:.2f}+{ROI_H:.2f} "
            f"LOW/HIGH={EDGE_T_LOW:.3f}/{EDGE_T_HIGH:.3f} DARK={DARK_LUMA:.2f} "
            f"LAPL={LAPL_VAR_MIN:.1f} N={edge_hist.maxlen}"
        ),
        flush=True,
    )

    while not _STOP:
        # Check for AI mode changes
        if sub_ai_mode:
            try:
                topic, payload = sub_ai_mode.recv(timeout_ms=10)
                if topic and payload and topic == TOPIC_SYSTEM_AI_MODE_CHANGED:
                    new_mode = payload.get("mode", "")
                    print(f"[obst] AI mode change detected: {new_mode}", flush=True)
                    old_active = detector_active
                    detector_active = new_mode == "local"
                    if old_active != detector_active:
                        if detector_active:
                            print("[obst] AI Mode: local - resuming local detector", flush=True)
                            # Reset state when resuming
                            edge_hist.clear()
                            last_present = False
                        else:
                            print("[obst] AI Mode: pc_offload - pausing local detector", flush=True)
            except Exception as e:
                # Ignore transient errors in AI mode subscription, but log for diagnosis
                print(f"[obst] Exception in AI mode subscription: {e}", file=sys.stderr, flush=True)

        # If detector is not active (pc_offload mode), sleep and continue
        if not detector_active:
            time.sleep(0.5)
            continue
        proc_mtime, proc_age_s = file_mtime_age(PROC_PATH)
        img_proc = load_gray(PROC_PATH)

        if img_proc is None:
            payload = {
                "type": "obstacle",
                "present": False,
                "confidence": 0.0,
                "edge_pct": 0.0,
                "edge_nz": 0,
                "roi": {"y0": 0, "y1": 0, "w": 0, "h": 0},
                "roi_norm": {"y0": ROI_Y0, "h": ROI_H},
                "ts": now_s(),
                "age_s": proc_age_s,
                "stale": proc_age_s > SNAP_MAX_AGE_S,
                "error": "proc_not_found",
            }
            atomic_write_json(OBSTACLE_JSON, payload)
            publish("vision.obstacle", payload)
            time.sleep(0.25)
            continue

        h, w = img_proc.shape[:2]
        sl = roi_slice(h, ROI_Y0, ROI_H)
        y0, y1 = sl.start, sl.stop

        edge_nz, roi_px, edge_pct_raw = edge_stats(img_proc, sl)
        edge_hist.append(float(edge_pct_raw))
        edge_pct = median_of(edge_hist)

        img_raw = load_gray(RAW_PATH)
        if img_raw is None:
            img_raw = img_proc
        mean_luma, lap_var = luma_and_focus(img_raw, sl)

        dark = mean_luma < DARK_LUMA
        blurry = lap_var < LAPL_VAR_MIN

        if dark or blurry:
            present = True
        else:
            if edge_pct <= EDGE_T_LOW:
                present = True
            elif edge_pct >= EDGE_T_HIGH:
                present = False
            else:
                present = last_present

        if present:
            base = 0.0
            if EDGE_T_LOW > 0:
                base = clamp((EDGE_T_LOW - edge_pct) / EDGE_T_LOW, 0.0, 1.0)
            occl = 1.0 if (dark or blurry) else 0.0
            conf = clamp(CONF_GAIN * base + 0.5 * occl, 0.0, 1.0)
        else:
            denom = max(1e-6, 1.0 - EDGE_T_HIGH)
            base = clamp((edge_pct - EDGE_T_HIGH) / denom, 0.0, 1.0)
            conf = clamp(CONF_GAIN * base, 0.0, 1.0)

        last_present = present

        if OBST_ANN:
            try:
                bins = bins_edge_pcts(img_proc, sl, OBST_BINS) if OBST_BINS > 0 else None
            except Exception:
                bins = None
            draw_overlay(
                base_gray=img_proc,  # annot na PROC
                sl=sl,
                present=present,
                confidence=float(conf),
                edge_pct=float(edge_pct),
                bins_pcts=bins,
                ann_path=OBST_ANN_PATH,
            )

        payload = {
            "type": "obstacle",
            "present": bool(present),
            "confidence": round(float(conf), 3),
            "edge_pct": round(float(edge_pct), 4),
            "edge_nz": int(edge_nz),
            "roi": {"y0": int(y0), "y1": int(y1), "w": int(w), "h": int(h)},
            "roi_norm": {"y0": ROI_Y0, "h": ROI_H},
            "ts": now_s(),
            "age_s": round(proc_age_s, 3),
            "stale": bool(proc_age_s > SNAP_MAX_AGE_S),
            "diag": {
                "edge_pct_raw": round(float(edge_pct_raw), 4),
                "roi_px": int(roi_px),
                "mean_luma": round(float(mean_luma), 3),
                "lap_var": round(float(lap_var), 1),
                "dark": bool(dark),
                "blurry": bool(blurry),
                "t_low": EDGE_T_LOW,
                "t_high": EDGE_T_HIGH,
                "conf_gain": CONF_GAIN,
                "edge_area_pct_legacy": EDGE_AREA_PCT,
                "edge_pix_min_legacy": EDGE_PIX_MIN,
                "proc_mtime": proc_mtime,
            },
        }

        atomic_write_json(OBSTACLE_JSON, payload)
        publish("vision.obstacle", payload)

        print(
            (
                f"[obst] snap present={payload['present']} conf={payload['confidence']:.2f} "
                f"pct={payload['edge_pct']:.3f}/{payload['diag']['edge_pct_raw']:.3f} "
                f"luma={payload['diag']['mean_luma']:.2f} lapv={payload['diag']['lap_var']:.1f} "
                f"dark={payload['diag']['dark']} blur={payload['diag']['blurry']} "
                f"roi=({y0}:{y1}/{h})"
            ),
            flush=True,
        )

        time.sleep(0.1)

    # Cleanup
    if sub_ai_mode:
        try:
            sub_ai_mode.close()
        except Exception as e:
            print(f"[obst] WARNING: Could not close AI mode subscription: {e}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
