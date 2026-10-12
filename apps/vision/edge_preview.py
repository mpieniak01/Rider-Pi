from __future__ import annotations

import os
import signal
import time

import cv2

from apps.vision.config import load_config

# Load configuration (TOML > ENV > defaults)
_cfg = load_config()
_edge_cfg = _cfg.edge_preview

SNAP_DIR = _edge_cfg.snap_dir
EDGE_LOW = _edge_cfg.edge_low
EDGE_HIGH = _edge_cfg.edge_high
SNAP_EVERY_MS = _edge_cfg.snap_every_ms
PREVIEW_ROT = _edge_cfg.preview_rot
PREVIEW_FLIP_H = _edge_cfg.preview_flip_h
FRAME_W = _edge_cfg.frame_w
FRAME_H = _edge_cfg.frame_h
LAST = _edge_cfg.last_frame

RAW = os.path.join(SNAP_DIR, "raw.jpg")
PROC = os.path.join(SNAP_DIR, "proc.jpg")
os.makedirs(SNAP_DIR, exist_ok=True)
os.makedirs(os.path.dirname(LAST), exist_ok=True)


def rot_flip(img):
    if PREVIEW_ROT == 90:
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    elif PREVIEW_ROT == 180:
        img = cv2.rotate(img, cv2.ROTATE_180)
    elif PREVIEW_ROT == 270:
        img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if PREVIEW_FLIP_H:
        img = cv2.flip(img, 1)
    return img


def save_jpeg(path, bgr, quality=85):
    ok, enc = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        return 0
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(enc.tobytes())
    os.replace(tmp, path)
    return len(enc)


def main():
    from apps.camera.utils import open_camera

    running = True

    def stop(*_):
        nonlocal running
        running = False

    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    for sig in previous:
        signal.signal(sig, stop)
    read = None
    period = SNAP_EVERY_MS / 1000.0
    next_t = last_ok = time.monotonic()
    try:
        read, _ = open_camera((FRAME_W, FRAME_H))
        print(f"[edge] start | SNAP_DIR={SNAP_DIR} | W×H={FRAME_W}x{FRAME_H}", flush=True)
        while running:
            try:
                ok, frame = read()
            except Exception:
                ok, frame = False, None
            now = time.monotonic()
            if not ok or frame is None:
                if now - last_ok >= 2:
                    read.close()
                    read = None
                    read, _ = open_camera((FRAME_W, FRAME_H))
                    last_ok = now
                time.sleep(0.02)
                continue
            last_ok = now
            raw = rot_flip(frame)
            save_jpeg(RAW, raw)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 1.0), EDGE_LOW, EDGE_HIGH)
            save_jpeg(PROC, rot_flip(cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)))
            save_jpeg(LAST, raw, quality=80)
            next_t += period
            delay = next_t - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_t = time.monotonic()
    finally:
        try:
            if read is not None:
                read.close()
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
