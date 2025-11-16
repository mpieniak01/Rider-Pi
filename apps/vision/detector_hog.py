#!/usr/bin/env python3
from __future__ import annotations

# apps/vision/detector_hog.py
import os
import time

import cv2
import numpy as np
from PIL import Image

from apps.vision.ai_mode_adapter import log_vision_mode_status, should_run_local_detectors
from common.bus import (
    TOPIC_PROVIDER_VISION_STATE,
    TOPIC_SYSTEM_AI_MODE_CHANGED,
    BusPub,
    BusSub,
)
from common.cam_heartbeat import CameraHB

PUB = BusPub()
HB = CameraHB(mode="hog")

SNAP_DIR = os.getenv("SNAP_BASE", "/home/pi/robot/snapshots")
PROC_FN = os.path.join(SNAP_DIR, "proc.jpg")

W, H = 320, 240
MAX_FPS = float(os.getenv("HOG_MAX_FPS", "4.0"))  # ~4 fps dla CPU/baterii


def open_camera(size=(W, H)):
    try:
        from picamera2 import Picamera2

        picam2 = Picamera2()
        cfg = picam2.create_preview_configuration(main={"size": size, "format": "RGB888"})
        picam2.configure(cfg)
        picam2.start()

        def read():
            arr = picam2.capture_array()
            return True, cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

        return read, size
    except Exception:
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])

        def read():
            return cap.read()

        return read, size


def save_jpeg_bgr(path: str, bgr: np.ndarray):
    tmp = path + ".tmp"
    Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)).save(tmp, "JPEG", quality=80)
    os.replace(tmp, path)


def main():
    # Log AI mode status at startup
    log_vision_mode_status()

    # Subscribe to AI/provider mode change events
    sub_ai_mode = None
    try:
        sub_ai_mode = BusSub([TOPIC_SYSTEM_AI_MODE_CHANGED, TOPIC_PROVIDER_VISION_STATE])
    except Exception as e:
        print(f"[hog] WARNING: Could not subscribe to AI/provider mode changes: {e}", flush=True)

    # Initial mode check
    detector_active = should_run_local_detectors()
    if not detector_active:
        print("[hog] AI Mode: pc_offload - local HOG detector paused, waiting for mode change", flush=True)
    else:
        print("[hog] AI Mode: local - running local HOG detector", flush=True)

    # Only initialize camera and HOG when in local mode initially
    read = None
    hog = None
    if detector_active:
        os.makedirs(SNAP_DIR, exist_ok=True)
        read, _ = open_camera()
        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

    last = time.time()
    ema = None
    # hej! od razu pierwsze HB
    HB.tick(None, 0.0, presenting=False)

    try:
        while True:
            # Check for AI/provider mode changes
            if sub_ai_mode:
                try:
                    topic, payload = sub_ai_mode.recv(timeout_ms=10)
                    if topic and payload:
                        if topic == TOPIC_SYSTEM_AI_MODE_CHANGED:
                            new_mode = payload.get("mode", "")
                            old_active = detector_active
                            detector_active = new_mode in ("local", "local_offload", "local_mode")
                            print(f"[hog] AI mode change detected: {new_mode}", flush=True)
                        elif topic == TOPIC_PROVIDER_VISION_STATE:
                            new_mode = payload.get("mode", "")
                            old_active = detector_active
                            detector_active = new_mode != "pc"
                            print(f"[hog] Provider vision state: {new_mode}", flush=True)
                        else:
                            continue
                        if old_active != detector_active:
                            if detector_active:
                                print("[hog] Vision provider: local - resuming local HOG detector", flush=True)
                                if read is None:
                                    os.makedirs(SNAP_DIR, exist_ok=True)
                                    read, _ = open_camera()
                                    hog = cv2.HOGDescriptor()
                                    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
                            else:
                                print("[hog] Vision provider: pc - pausing local HOG detector", flush=True)
                except Exception as e:
                    # Ignore errors during AI mode change handling, but log for debugging
                    print(f"[hog] Exception in AI mode change handler: {e}", flush=True)

            # If detector is not active (pc_offload mode), sleep and continue
            if not detector_active:
                time.sleep(0.5)
                continue

            # Skip if camera not initialized
            if read is None or hog is None:
                time.sleep(0.1)
                continue

            t0 = time.time()
            ok, frame = read()
            if not ok:
                time.sleep(0.01)
                continue

        # skala 1.05…1.1, minNeighbors=4–6; 320x240 i tak ogranicza koszt
        rects, weights = hog.detectMultiScale(frame, winStride=(8, 8), padding=(8, 8), scale=1.05)
        out = frame.copy()
        max_score = 0.0
        for (x, y, w, h), s in zip(rects, weights, strict=False):
            max_score = max(max_score, float(s))
            cv2.rectangle(out, (x, y), (x + w, y + h), (0, 255, 255), 2)
            # opcjonalna etykieta
            cv2.putText(
                out,
                f"{s:.2f}",
                (x, y - 4),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 255, 255),
                1,
                cv2.LINE_AA,
            )

        # publikuj presence dla “person”
        present = len(rects) > 0
        if present:
            PUB.publish(
                "vision.person",
                {
                    "present": True,
                    "score": float(max_score),
                    "count": int(len(rects)),
                    "bbox": [
                        int(rects[0][0]),
                        int(rects[0][1]),
                        int(rects[0][2]),
                        int(rects[0][3]),
                    ],
                    "mode": "hog",
                },
                add_ts=True,
            )

        # zapisz PROC do podglądu na dashboardzie
        try:
            save_jpeg_bgr(PROC_FN, out)
        except Exception as e:
            print("[hog] save error:", e, flush=True)

        # heartbeat (fps)
        now = time.time()
        dt = max(1e-6, now - last)
        inst = 1.0 / dt
        ema = inst if ema is None else (0.9 * ema + 0.1 * inst)
        last = now
        HB.tick(out, ema, presenting=False)

        # throtlling dla CPU/baterii
        min_dt = 1.0 / MAX_FPS
        spent = time.time() - t0
        if spent < min_dt:
            time.sleep(min_dt - spent)
    finally:
        # Cleanup
        if sub_ai_mode:
            try:
                sub_ai_mode.close()
            except Exception:
                pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
