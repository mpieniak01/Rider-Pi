#!/usr/bin/env python3
# apps/vision/detector_hog.py
import os, time, cv2, numpy as np
from typing import Tuple
from PIL import Image

from common.bus import BusPub
from common.cam_heartbeat import CameraHB

PUB = BusPub()
HB  = CameraHB(mode="hog")

SNAP_DIR = os.getenv("SNAP_BASE", "/home/pi/robot/snapshots")
PROC_FN  = os.path.join(SNAP_DIR, "proc.jpg")

W, H = 320, 240
MAX_FPS = float(os.getenv("HOG_MAX_FPS", "4.0"))  # ~4 fps dla CPU/baterii

def open_camera(size=(W, H)):
    try:
        from picamera2 import Picamera2
        picam2 = Picamera2()
        cfg = picam2.create_preview_configuration(main={"size": size, "format": "RGB888"})
        picam2.configure(cfg); picam2.start()
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
    os.makedirs(SNAP_DIR, exist_ok=True)
    read, _ = open_camera()
    hog = cv2.HOGDescriptor()
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

    last = time.time(); ema = None
    # hej! od razu pierwsze HB
    HB.tick(None, 0.0, presenting=False)

    while True:
        t0 = time.time()
        ok, frame = read()
        if not ok:
            time.sleep(0.01); continue

        # skala 1.05…1.1, minNeighbors=4–6; 320x240 i tak ogranicza koszt
        rects, weights = hog.detectMultiScale(frame, winStride=(8,8), padding=(8,8), scale=1.05)
        out = frame.copy()
        max_score = 0.0
        for (x,y,w,h), s in zip(rects, weights):
            max_score = max(max_score, float(s))
            cv2.rectangle(out, (x,y), (x+w,y+h), (0,255,255), 2)
            # opcjonalna etykieta
            cv2.putText(out, f"{s:.2f}", (x, y-4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0,255,255), 1, cv2.LINE_AA)

        # publikuj presence dla “person”
        present = len(rects) > 0
        if present:
            PUB.publish("vision.person", {
                "present": True,
                "score": float(max_score),
                "count": int(len(rects)),
                "bbox": [int(rects[0][0]), int(rects[0][1]), int(rects[0][2]), int(rects[0][3])],
                "mode": "hog"
            }, add_ts=True)

        # zapisz PROC do podglądu na dashboardzie
        try: save_jpeg_bgr(PROC_FN, out)
        except Exception as e: print("[hog] save error:", e, flush=True)

        # heartbeat (fps)
        now = time.time()
        dt = max(1e-6, now - last)
        inst = 1.0 / dt
        ema = inst if ema is None else (0.9*ema + 0.1*inst)
        last = now
        HB.tick(out, ema, presenting=False)

        # throtlling dla CPU/baterii
        min_dt = 1.0 / MAX_FPS
        spent = time.time() - t0
        if spent < min_dt:
            time.sleep(min_dt - spent)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
