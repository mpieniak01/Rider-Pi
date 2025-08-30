#!/usr/bin/env python3
# apps/camera/preview_lcd_ssd.py
# Preview + MobileNet-SSD (Caffe). Publikuje vision.person dla wykryć „person”.
# + wysyła camera.heartbeat (w,h,mode,fps,lcd.{active,presenting,rot})
# + snapshoty: RAW/proc/LCD(our)/LCD_fb

import os, time, json
from typing import Tuple, List, Set
import numpy as np
import cv2

from common.bus import BusPub, now_ts
from common.cam_heartbeat import CameraHB
from common.snap import Snapper

PUB = BusPub()
HB  = CameraHB(mode="ssd")
SNAP = Snapper(base_dir=os.getenv("SNAP_BASE", "/home/pi/robot/snapshots"))

def pub(topic: str, payload: dict, add_ts: bool = False):
    try:
        PUB.publish(topic, payload, add_ts=add_ts)
    except Exception:
        pass

DISABLE_LCD = os.getenv("DISABLE_LCD", "0") == "1"
NO_DRAW     = os.getenv("NO_DRAW", "0") == "1"

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
        lcd.rotation = 270 if str(os.getenv("PREVIEW_ROT","270")) == "270" else 0
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

def open_camera(size=(320,240)):
    try:
        from picamera2 import Picamera2
        picam2 = Picamera2()
        config = picam2.create_preview_configuration(main={"size": size, "format":"RGB888"})
        picam2.configure(config)
        picam2.start()
        def read():
            arr = picam2.capture_array()
            return True, cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        return read, size
    except Exception:
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0]); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])
        def read():
            return cap.read()
        return read, size

CLASSES = [
    "background","aeroplane","bicycle","bird","boat","bottle","bus","car","cat",
    "chair","cow","diningtable","dog","horse","motorbike","person","pottedplant",
    "sheep","sofa","train","tvmonitor"
]
PERSON_ID = 15

def load_ssd():
    proto = os.path.join("models","ssd","MobileNetSSD_deploy.prototxt")
    model = os.path.join("models","ssd","MobileNetSSD_deploy.caffemodel")
    if not (os.path.isfile(proto) and os.path.isfile(model)):
        raise FileNotFoundError("Brak modeli SSD w models/ssd/")
    net = cv2.dnn.readNetFromCaffe(proto, model)
    return net

def parse_classes_env() -> Set[str]:
    raw = os.getenv("SSD_CLASSES", "person")
    return set([x.strip().lower() for x in raw.split(",") if x.strip()])

def main():
    rot   = int(os.getenv("PREVIEW_ROT", "270"))
    SCORE = float(os.getenv("SSD_SCORE", "0.55"))
    EVERY = int(os.getenv("SSD_EVERY", "2"))
    CLW   = parse_classes_env()

    read, size = open_camera((320,240))
    net = load_ssd()

    frame_id = 0
    t0, frames = time.time(), 0
    fps_ema, prev_t = None, time.time()

    # pierwszy HB
    HB.tick(None, 0.0, presenting=not NO_DRAW)

    while True:
        ok, frame = read()
        if not ok:
            time.sleep(0.01); continue

        if rot in (90, 180, 270):
            if rot == 90:   frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            elif rot == 180:frame = cv2.rotate(frame, cv2.ROTATE_180)
            elif rot == 270:frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

        # FPS (EMA)
        now = time.time()
        dt = max(1e-6, now - prev_t)
        inst = 1.0/dt
        fps_ema = inst if fps_ema is None else (0.9*fps_ema + 0.1*inst)
        prev_t = now

        out = frame.copy()

        do_detect = (frame_id % max(1,EVERY) == 0)
        detections = []

        if do_detect:
            blob = cv2.dnn.blobFromImage(cv2.resize(frame,(300,300)), 0.007843, (300,300), 127.5, swapRB=True, crop=False)
            net.setInput(blob)
            det = net.forward()
            h, w = frame.shape[:2]
            for i in range(det.shape[2]):
                conf = float(det[0,0,i,2])
                if conf < SCORE: continue
                cls_id = int(det[0,0,i,1])
                x1 = int(det[0,0,i,3]*w); y1 = int(det[0,0,i,4]*h)
                x2 = int(det[0,0,i,5]*w); y2 = int(det[0,0,i,6]*h)
                name = CLASSES[cls_id] if 0 <= cls_id < len(CLASSES) else str(cls_id)
                if CLW and (name.lower() not in CLW): continue
                detections.append((name, conf, (x1,y1,x2,y2)))

        for name, conf, (x1,y1,x2,y2) in detections:
            if not NO_DRAW:
                cv2.rectangle(out, (x1,y1), (x2,y2), (0,255,255), 2)
                cv2.putText(out, f"{name}:{conf:.2f}", (x1,max(0,y1-5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,255), 1, cv2.LINE_AA)
            if name.lower() == "person":
                pub("vision.person", {
                    "present": True,
                    "score": float(conf),
                    "bbox": [int(x1), int(y1), int(x2-x1), int(y2-y1)]
                }, add_ts=True)

        # --- SNAPSHOTS ---
        SNAP.cam(frame)
        SNAP.proc(out)
        SNAP.lcd_from_frame(out)
        SNAP.lcd_from_fb()

        lcd_show_bgr(out)
        HB.tick(out, fps_ema, presenting=not NO_DRAW)

        frame_id += 1
        frames += 1
        if frames % 60 == 0:
            dt_all = time.time() - t0
            fps = frames/dt_all if dt_all > 0 else 0.0
            print(f"[ssd] fps={fps:.1f} (every={EVERY}, score>={SCORE})", flush=True)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
