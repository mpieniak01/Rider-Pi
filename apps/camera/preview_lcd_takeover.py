#!/usr/bin/env python3
# apps/camera/preview_lcd_takeover.py
# Szybki preview na LCD + HAAR face; publikuje vision.face (present/score/count)
# + wysyła camera.heartbeat (w,h,mode,fps,lcd.{active,presenting,rot})
# + snapshoty: RAW/proc/LCD(our)/LCD_fb

import os, time, json
from typing import Tuple
import numpy as np
import cv2

# --- BUS (multipart PUB) ---
from common.bus import BusPub, now_ts
from common.cam_heartbeat import CameraHB  # wspólny emiter heartbeatów
from common.snap import Snapper

PUB = BusPub()
HB  = CameraHB(mode="haar")
SNAP = Snapper(base_dir=os.getenv("SNAP_BASE", "/home/pi/robot/snapshots"))

def pub(topic: str, payload: dict, add_ts: bool = False):
    try:
        PUB.publish(topic, payload, add_ts=add_ts)
    except Exception:
        pass

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

# --- Kamera (Picamera2 -> fallback VideoCapture) ---
def open_camera(size=(320,240)) -> Tuple[object, Tuple[int,int]]:
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
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])
        def read():
            return cap.read()
        return read, size

# --- HAAR ---
def load_haar():
    xml = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
    clf = cv2.CascadeClassifier(xml)
    if clf.empty():
        raise RuntimeError("Cannot load HAAR cascade")
    return clf

def main():
    rot = int(os.getenv("PREVIEW_ROT", "270"))
    read, size = open_camera((320,240))
    haar = load_haar()

    prev_t  = time.time()
    fps_ema = None
    t0 = time.time()
    frames = 0

    # pierwszy heartbeat (od razu po starcie)
    try:
        HB.tick(None, 0.0, presenting=not NO_DRAW)
    except Exception:
        pass

    while True:
        ok, frame = read()
        if not ok:
            time.sleep(0.01)
            continue

        if rot in (90, 180, 270):
            if rot == 90:
                frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            elif rot == 180:
                frame = cv2.rotate(frame, cv2.ROTATE_180)
            elif rot == 270:
                frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

        # FPS (EMA)
        now = time.time()
        dt = max(1e-6, now - prev_t)
        inst = 1.0 / dt
        fps_ema = inst if fps_ema is None else (0.9 * fps_ema + 0.1 * inst)
        prev_t = now

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = haar.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30,30))

        out = frame.copy()
        if not NO_DRAW:
            for (x,y,w,h) in faces:
                cv2.rectangle(out, (x,y), (x+w,y+h), (0,255,0), 2)

        if len(faces) > 0:
            pub("vision.face", {"present": True, "score": 0.9, "count": int(len(faces))}, add_ts=True)

        # --- SNAPSHOTS ---
        SNAP.cam(frame)               # RAW z kamery
        SNAP.proc(out)                # po obróbce
        SNAP.lcd_from_frame(out)      # co my byśmy narysowali
        SNAP.lcd_from_fb()            # realny LCD (framebuffer), jeśli jest

        # render na LCD + heartbeat
        lcd_show_bgr(out)
        HB.tick(out, fps_ema, presenting=not NO_DRAW)

        frames += 1
        if frames % 60 == 0:
            dt_all = time.time() - t0
            fps = frames/dt_all if dt_all > 0 else 0.0
            print(f"[takeover] fps={fps:.1f}", flush=True)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
