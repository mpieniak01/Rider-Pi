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
import os
import signal
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

import cv2  # type: ignore
import numpy as np

try:
    import zmq  # type: ignore
except Exception:  # pragma: no cover
    zmq = None  # type: ignore

from apps.vision.ai_mode_adapter import log_vision_mode_status, should_run_local_detectors
from apps.vision.config import load_config
from common.bus import (
    TOPIC_PROVIDER_VISION_STATE,
    TOPIC_SYSTEM_AI_MODE_CHANGED,
    BusSub,
)
from common.data_quality import finite_number, sample_status
from common.frame_stream import FrameStreamClient

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

FRAME_STREAM_ADDR = os.getenv("OBST_FRAME_STREAM_ADDR", os.getenv("FRAME_STREAM_ADDR", "tcp://127.0.0.1:5562"))
FRAME_STREAM_TOPIC = os.getenv("OBST_FRAME_STREAM_TOPIC", os.getenv("FRAME_STREAM_TOPIC", "camera.frame.raw"))
FRAME_STREAM_TIMEOUT_MS = int(os.getenv("OBST_FRAME_STREAM_TIMEOUT_MS", "200"))
USE_FRAME_STREAM = os.getenv("OBST_USE_FRAME_STREAM", "1") == "1"
STREAM_CANNY_LOW = int(os.getenv("OBST_CANNY_LOW", "40"))
STREAM_CANNY_HIGH = int(os.getenv("OBST_CANNY_HIGH", "120"))
_LAST_STREAM_FRAME: np.ndarray | None = None

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


def copy_raw_snapshot(message: str | None = None) -> None:
    try:
        frame = None
        if _LAST_STREAM_FRAME is not None:
            frame = _LAST_STREAM_FRAME.copy()
        if frame is None:
            frame = cv2.imread(RAW_PATH)
            if frame is None:
                return
        if message:
            cv2.putText(
                frame,
                message,
                (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
        cv2.imwrite(OBST_ANN_PATH, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    except Exception as exc:
        print(f"[obst][annot] idle copy failed: {exc}", flush=True)


# ----------------------------- optional bus ---------------------------------

_bus = None
if PUBLISH:
    try:
        if zmq is None:
            raise RuntimeError("pyzmq unavailable")
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


def _poll_obstacle_mode(sub_ai_mode, detector_active, edge_hist, edge_times, last_present):
    # Check for AI mode/provider changes
    if not sub_ai_mode:
        return detector_active, last_present, False
    try:
        topic, payload = sub_ai_mode.recv(timeout_ms=10)
        if not (topic and payload):
            return detector_active, last_present, False
        if topic == TOPIC_SYSTEM_AI_MODE_CHANGED:
            new_mode = payload.get("mode", "")
            old_active = detector_active
            detector_active = new_mode in ("local", "local_offload", "local_mode")
            print(f"[obst] AI mode event: {new_mode}", flush=True)
        elif topic == TOPIC_PROVIDER_VISION_STATE:
            new_mode = payload.get("mode", "")
            old_active = detector_active
            detector_active = new_mode != "pc"
            print(f"[obst] Provider vision state: {new_mode}", flush=True)
        else:
            return detector_active, last_present, True
        if old_active != detector_active:
            if detector_active:
                print("[obst] Vision provider: local - resuming detector", flush=True)
                edge_hist.clear()
                edge_times.clear()
                last_present = False
            else:
                print("[obst] Vision provider: pc - pausing local detector", flush=True)
    except Exception as e:
        # Ignore transient errors in AI mode subscription, but log for diagnosis
        print(f"[obst] Exception in AI mode subscription: {e}", file=sys.stderr, flush=True)

    return detector_active, last_present, False


def _write_paused_obstacle():
    copy_raw_snapshot("PC offload")
    payload = {
        "type": "obstacle",
        "present": False,
        "confidence": 0.0,
        "edge_pct": 0.0,
        "roi": {"y0": 0, "y1": 0, "w": 0, "h": 0},
        "roi_norm": {"y0": ROI_Y0, "h": ROI_H},
        "ts": now_s(),
        "age_s": 0.0,
        "stale": False,
        "observed_at": None,
        "data_ready": False,
        "error": "local_detector_paused",
        "source": "pc_offload",
    }
    atomic_write_json(OBSTACLE_JSON, payload)


def _save_stream_obstacle_image(img_proc, frame_quality, proc_mtime):
    if PROC_PATH:
        try:
            if frame_quality["ready"]:
                cv2.imwrite(PROC_PATH, img_proc, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                os.utime(PROC_PATH, (proc_mtime, proc_mtime))
            elif Path(PROC_PATH).exists():
                # A derived file cannot erase an explicit capture fault
                # after stream/process restart and file fallback.
                os.utime(PROC_PATH, (0, 0))
        except Exception as e:
            print(f"[obst] WARNING: Could not save processed image to {PROC_PATH}: {e}", flush=True)


def _publish_missing_obstacle(proc_age_s, frame_stream):
    payload = {
        "type": "obstacle",
        "present": False,
        "confidence": 0.0,
        "edge_pct": 0.0,
        "edge_nz": 0,
        "roi": {"y0": 0, "y1": 0, "w": 0, "h": 0},
        "roi_norm": {"y0": ROI_Y0, "h": ROI_H},
        "ts": now_s(),
        "age_s": round(proc_age_s, 3) if finite_number(proc_age_s) else None,
        "stale": proc_age_s > SNAP_MAX_AGE_S,
        "error": "proc_not_found" if frame_stream is None else "stream_no_frame",
        "observed_at": None,
        "data_ready": False,
    }
    atomic_write_json(OBSTACLE_JSON, payload)
    publish("vision.obstacle", payload)
    publish(
        "obstacle.map",
        {
            "present": False,
            "confidence": 0.0,
            "edge_pct": 0.0,
            "ts": payload["ts"],
            "source": "obstacle_roi",
            "error": payload.get("error", "missing_frame"),
            "observed_at": None,
            "data_ready": False,
        },
    )
    time.sleep(0.25)


def _receive_obstacle_frame(frame_stream):
    global _LAST_STREAM_FRAME
    img_proc = None
    img_raw_gray = None
    proc_age_s = float("inf")
    proc_mtime = None
    source_payload = {}

    frame_bgr = None
    if frame_stream is not None:
        frame_bgr = frame_stream.recv(FRAME_STREAM_TIMEOUT_MS)
        if frame_bgr is not None:
            source_payload = frame_stream.metadata
            frame_quality = sample_status(source_payload, max_age_s=SNAP_MAX_AGE_S)
            proc_mtime = frame_quality["observed_at"]
            proc_age_s = frame_quality["age_s"] if frame_quality["age_s"] is not None else float("inf")
            _LAST_STREAM_FRAME = frame_bgr.copy()
            img_raw_gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
            blur = cv2.GaussianBlur(img_raw_gray, (5, 5), 1.0)
            img_proc = cv2.Canny(blur, STREAM_CANNY_LOW, STREAM_CANNY_HIGH)
            _save_stream_obstacle_image(img_proc, frame_quality, proc_mtime)

    if img_proc is None:
        proc_mtime, proc_age_s = file_mtime_age(PROC_PATH)
        source_payload = {"observed_at": proc_mtime}
        img_proc = load_gray(PROC_PATH)
        if img_proc is None:
            _publish_missing_obstacle(proc_age_s, frame_stream)
            return None
        img_raw_gray = load_gray(RAW_PATH)

    return img_proc, img_raw_gray, proc_mtime, proc_age_s, source_payload


def _update_obstacle_history(source_payload, proc_mtime, edge_pct_raw, edge_hist, edge_times):
    source_quality = sample_status(source_payload, max_age_s=SNAP_MAX_AGE_S)
    if not source_quality["ready"] or (edge_times and proc_mtime < edge_times[-1]):
        edge_hist.clear()
        edge_times.clear()
    if source_quality["ready"] and (not edge_times or proc_mtime > edge_times[-1]):
        edge_hist.append(float(edge_pct_raw))
        edge_times.append(proc_mtime)


def _obstacle_presence_confidence(edge_pct, dark, blurry, last_present):
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

    return present, conf


def _annotate_obstacle(img_proc, sl, present, conf, edge_pct):
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


def _process_obstacle_frame(sample, edge_hist, edge_times, last_present):
    img_proc, img_raw_gray, proc_mtime, proc_age_s, source_payload = sample
    h, w = img_proc.shape[:2]
    sl = roi_slice(h, ROI_Y0, ROI_H)
    y0, y1 = sl.start, sl.stop

    edge_nz, roi_px, edge_pct_raw = edge_stats(img_proc, sl)
    _update_obstacle_history(source_payload, proc_mtime, edge_pct_raw, edge_hist, edge_times)
    edge_pct = median_of(edge_hist)

    if img_raw_gray is None:
        img_raw_gray = img_proc
    mean_luma, lap_var = luma_and_focus(img_raw_gray, sl)

    dark = mean_luma < DARK_LUMA
    blurry = lap_var < LAPL_VAR_MIN

    present, conf = _obstacle_presence_confidence(edge_pct, dark, blurry, last_present)
    last_present = present

    _annotate_obstacle(img_proc, sl, present, conf, edge_pct)

    observed_at = min(edge_times) if edge_times else proc_mtime
    frame_quality = sample_status(dict(source_payload, observed_at=observed_at), max_age_s=SNAP_MAX_AGE_S)
    payload = {
        "type": "obstacle",
        "present": bool(present),
        "confidence": round(float(conf), 3),
        "edge_pct": round(float(edge_pct), 4),
        "edge_nz": int(edge_nz),
        "roi": {"y0": int(y0), "y1": int(y1), "w": int(w), "h": int(h)},
        "roi_norm": {"y0": ROI_Y0, "h": ROI_H},
        "ts": now_s(),
        "age_s": round(proc_age_s, 3) if finite_number(proc_age_s) else None,
        "stale": not frame_quality["ready"],
        "observed_at": observed_at,
        "data_ready": frame_quality["ready"],
        "error": source_payload["error"]
        if isinstance(source_payload.get("error"), str) and source_payload["error"].strip()
        else frame_quality["error"],
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
    publish(
        "obstacle.map",
        {
            "present": bool(present),
            "confidence": round(float(conf), 3),
            "edge_pct": round(float(edge_pct), 4),
            "ts": payload["ts"],
            "source": "obstacle_roi",
            "roi": payload["roi_norm"],
            "observed_at": payload["observed_at"],
            "data_ready": payload["data_ready"],
            "stale": payload["stale"],
            "error": payload["error"],
        },
    )

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

    return last_present


def _open_obstacle_frame_stream():
    frame_stream: FrameStreamClient | None = None
    if USE_FRAME_STREAM:
        try:
            frame_stream = FrameStreamClient(FRAME_STREAM_ADDR, FRAME_STREAM_TOPIC, return_last=True, copy_frame=True)
            print(
                f"[obst] frame stream subscribed: {FRAME_STREAM_ADDR} topic={FRAME_STREAM_TOPIC}",
                flush=True,
            )
        except Exception as exc:
            frame_stream = None
            print(f"[obst] WARN: frame stream disabled ({exc})", flush=True)

    return frame_stream


def main() -> int:
    global _LAST_STREAM_FRAME
    signal.signal(signal.SIGINT, _sigint)
    signal.signal(signal.SIGTERM, _sigint)

    # Log AI mode status at startup
    log_vision_mode_status()

    # Subscribe to AI mode/provider change events
    sub_ai_mode = None
    try:
        sub_ai_mode = BusSub([TOPIC_SYSTEM_AI_MODE_CHANGED, TOPIC_PROVIDER_VISION_STATE])
    except Exception as e:
        print(f"[obst] WARNING: Could not subscribe to AI/provider mode changes: {e}", flush=True)

    # Initial mode check
    detector_active = should_run_local_detectors()
    if not detector_active:
        print("[obst] AI Mode: pc_offload - local detector paused, waiting for mode change", flush=True)
    else:
        print("[obst] AI Mode: local - running local detector", flush=True)

    edge_hist = deque(maxlen=max(1, OBST_DEC_N))
    edge_times = deque(maxlen=edge_hist.maxlen)
    last_present = False

    print(
        (
            f"[obst] start PROC={PROC_PATH} RAW={RAW_PATH} ROI={ROI_Y0:.2f}+{ROI_H:.2f} "
            f"LOW/HIGH={EDGE_T_LOW:.3f}/{EDGE_T_HIGH:.3f} DARK={DARK_LUMA:.2f} "
            f"LAPL={LAPL_VAR_MIN:.1f} N={edge_hist.maxlen}"
        ),
        flush=True,
    )

    frame_stream = _open_obstacle_frame_stream()

    while not _STOP:
        detector_active, last_present, skip = _poll_obstacle_mode(
            sub_ai_mode, detector_active, edge_hist, edge_times, last_present
        )
        if skip:
            continue

        # If detector is not active (pc_offload mode), sleep and continue
        if not detector_active:
            _write_paused_obstacle()
            time.sleep(0.5)
            continue
        sample = _receive_obstacle_frame(frame_stream)
        if sample is None:
            continue
        last_present = _process_obstacle_frame(sample, edge_hist, edge_times, last_present)
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
