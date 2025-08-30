#!/usr/bin/env python3
# apps/camera/preview_lcd_hybrid.py
# PoC: SSD do inicjalizacji, tracker do podtrzymania, opcjonalny HAAR w ROI.
# Publikuje vision.person (tracker/SSD) i vision.face (HAAR).
# + wysyła camera.heartbeat + snapshoty RAW/proc/LCD/LCD_fb

import os
import time
from typing import Tuple, Optional

import cv2
import numpy as np

from common.bus import BusPub, now_ts
from common.cam_heartbeat import CameraHB
from common.snap import Snapper

PUB = BusPub()
HB = CameraHB(mode="hybrid")
SNAP = Snapper(base_dir=os.getenv("SNAP_BASE", "/home/pi/robot/snapshots"))


def pub(topic, payload: dict, add_ts: bool = False):
    try:
        PUB.publish(topic, payload, add_ts=add_ts)
    except Exception:
        pass


# --------- ORIENTATION (wspólne) ---------
def _env_flag(name: str, default: bool = False) -> bool:
    return str(os.getenv(name, str(int(default)))).lower() in ("1", "true", "yes", "y", "on")


ROT = int(os.getenv("PREVIEW_ROT", "270"))          # 0/90/180/270
FLIP_H = _env_flag("PREVIEW_FLIP_H", False)
FLIP_V = _env_flag("PREVIEW_FLIP_V", False)


def apply_rotation(frame, rot: int, flip_h: bool, flip_v: bool):
    if rot in (90, 180, 270):
        k = {
            90: cv2.ROTATE_90_CLOCKWISE,
            180: cv2.ROTATE_180,
            270: cv2.ROTATE_90_COUNTERCLOCKWISE,
        }[rot]
        frame = cv2.rotate(frame, k)
    if flip_h:
        frame = cv2.flip(frame, 1)
    if flip_v:
        frame = cv2.flip(frame, 0)
    return frame


# --- LCD (opcjonalnie) ---
DISABLE_LCD = os.getenv("DISABLE_LCD", "0") == "1"
NO_DRAW = os.getenv("NO_DRAW", "0") == "1"


def _lcd_init():
    if DISABLE_LCD:
        return None
    try:
        from xgoscreen.LCD_2inch import LCD_2inch
    except Exception:
        try:
            import xgoscreen.LCD_2inch as lcd_mod
            LCD_2inch = lcd_mod.LCD_2inch
        except Exception:
            return None
    try:
        lcd = LCD_2inch()
        lcd.rotation = 0  # obraz już obrócony w OpenCV
        return lcd
    except Exception:
        return None


_LCD = _lcd_init()


def lcd_show_bgr(img_bgr: np.ndarray):
    if _LCD is None:
        return
    from PIL import Image

    img = cv2.resize(img_bgr, (320, 240), interpolation=cv2.INTER_LINEAR)
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    _LCD.ShowImage(Image.fromarray(img_rgb))


def open_camera(size=(320, 240)):
    try:
        from picamera2 import Picamera2

        picam2 = Picamera2()
        config = picam2.create_preview_configuration(main={"size": size, "format": "RGB888"})
        picam2.configure(config)
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


CLASSES = [
    "background", "aeroplane", "bicycle", "bird", "boat", "bottle", "bus", "car", "cat",
    "chair", "cow", "diningtable", "dog", "horse", "motorbike", "person", "pottedplant",
    "sheep", "sofa", "train", "tvmonitor"
]
PERSON_ID = 15


def load_ssd():
    proto = os.path.join("models", "ssd", "MobileNetSSD_deploy.prototxt")
    model = os.path.join("models", "ssd", "MobileNetSSD_deploy.caffemodel")
    if not (os.path.isfile(proto) and os.path.isfile(model)):
        raise FileNotFoundError("Brak modeli SSD w models/ssd/")
    net = cv2.dnn.readNetFromCaffe(proto, model)
    return net


def create_tracker():
    typ = os.getenv("TRACKER", "KCF").upper()
    maker = None
    if hasattr(cv2, "legacy") and hasattr(cv2.legacy, f"Tracker{typ}_create"):
        maker = getattr(cv2.legacy, f"Tracker{typ}_create")
    elif hasattr(cv2, f"Tracker{typ}_create"):
        maker = getattr(cv2, f"Tracker{typ}_create")
    else:
        maker = getattr(cv2, "TrackerKCF_create", None) or getattr(getattr(cv2, "legacy", object), "TrackerKCF_create", None)
    if maker is None:
        raise RuntimeError("OpenCV tracker API not available")
    return maker()


def load_haar():
    xml = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
    clf = cv2.CascadeClassifier(xml)
    return clf if not clf.empty() else None


def main():
    SCORE = float(os.getenv("SSD_SCORE", "0.55"))
    EVERY = int(os.getenv("SSD_EVERY", "3"))
    HAAR_IN_ROI = os.getenv("HYBRID_HAAR", "1") == "1"
    LOG_EVERY = int(os.getenv("LOG_EVERY", "20"))

    read, size = open_camera((320, 240))
    net = load_ssd()

    tracker = None
    track_ok = False
    track_bbox = None
    haar = load_haar() if HAAR_IN_ROI else None

    t0, frames, fid = time.time(), 0, 0
    fps_ema = None
    prev_t = time.time()

    HB.tick(None, 0.0, presenting=not NO_DRAW)

    while True:
        ok, frame = read()
        if not ok:
            time.sleep(0.01)
            continue

        # >>> ORIENTACJA: po odczycie <<<
        frame = apply_rotation(frame, ROT, FLIP_H, FLIP_V)

        out = frame.copy()
        h, w = out.shape[:2]

        # FPS EMA
        now = time.time()
        dt = max(1e-6, now - prev_t)
        inst = 1.0 / dt
        fps_ema = inst if fps_ema is None else (0.9 * fps_ema + 0.1 * inst)
        prev_t = now

        # tracker
        if tracker is not None:
            track_ok, box = tracker.update(out)
            if track_ok:
                x, y, tw, th = [int(v) for v in box]
                track_bbox = (x, y, tw, th)
                if not NO_DRAW:
                    cv2.rectangle(out, (x, y), (x + tw, y + th), (255, 200, 0), 2)
                pub("vision.person", {"present": True, "score": 0.75, "bbox": [x, y, tw, th]}, add_ts=True)
            else:
                tracker = None
                track_bbox = None

        # SSD co N klatek
        if fid % max(1, EVERY) == 0:
            blob = cv2.dnn.blobFromImage(
                cv2.resize(out, (300, 300)), 0.007843, (300, 300), 127.5, swapRB=True, crop=False
            )
            net.setInput(blob)
            det = net.forward()
            best = None
            for i in range(det.shape[2]):
                conf = float(det[0, 0, i, 2])
                if conf < SCORE:
                    continue
                cls_id = int(det[0, 0, i, 1])
                if cls_id != PERSON_ID:
                    continue
                x1 = int(det[0, 0, i, 3] * w)
                y1 = int(det[0, 0, i, 4] * h)
                x2 = int(det[0, 0, i, 5] * w)
                y2 = int(det[0, 0, i, 6] * h)
                if best is None or conf > best[0]:
                    best = (conf, (x1, y1, x2, y2))

            if best is not None:
                conf, (bx1, by1, bx2, by2) = best
                if not NO_DRAW:
                    cv2.rectangle(out, (bx1, by1), (bx2, by2), (0, 255, 255), 2)
                pub("vision.person", {"present": True, "score": float(conf),
                                      "bbox": [bx1, by1, bx2 - bx1, by2 - by1]}, add_ts=True)
                tracker = create_tracker()
                tracker.init(out, (bx1, by1, bx2 - bx1, by2 - by1))
                track_bbox = (bx1, by1, bx2 - bx1, by2 - by1)

        # HAAR w ROI
        if haar is not None and track_bbox is not None:
            x, y, tw, th = track_bbox
            x0, y0, x1, y1 = max(0, x), max(0, y), min(w, x + tw), min(h, y + th)
            roi = out[y0:y1, x0:x1]
            if roi.size > 0:
                gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                faces = haar.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(20, 20))
                if not NO_DRAW:
                    for (fx, fy, fw, fh) in faces:
                        cv2.rectangle(out, (x0 + fx, y0 + fy), (x0 + fx + fw, y0 + fy + fh), (0, 255, 0), 2)
                if len(faces) > 0:
                    pub("vision.face", {"present": True, "score": 0.85, "count": len(faces)}, add_ts=True)

        # --- SNAPSHOTS ---
        SNAP.cam(frame)          # RAW po ROT/FLIP
        SNAP.proc(out)
        SNAP.lcd_from_frame(out)
        SNAP.lcd_from_fb()

        lcd_show_bgr(out)
        HB.tick(out, fps_ema, presenting=not NO_DRAW)

        fid += 1
        frames += 1
        if LOG_EVERY > 0 and (frames % LOG_EVERY == 0):
            dt_all = time.time() - t0
            fps = frames / dt_all if dt_all > 0 else 0.0
            print(f"[hybrid] fps={fps:.1f} (every={EVERY}, score>={SCORE})", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
