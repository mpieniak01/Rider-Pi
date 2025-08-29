#!/usr/bin/env python3
# apps/camera/preview_lcd_takeover.py
# Szybki preview na LCD + HAAR face; publikuje vision.face (present/score/count)

import os, time, json
from typing import Tuple
import numpy as np
import cv2

# --- BUS PUB helper (ZMQ) ---
try:
    import zmq
except Exception:
    zmq = None

def _bus_pub():
    if zmq is None:
        return None
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.PUB)
    s.connect(f"tcp://127.0.0.1:{os.getenv('BUS_PUB_PORT','5555')}")
    return s
_BUS = _bus_pub()

def pub(topic, payload: dict):
    try:
        if _BUS is not None:
            _BUS.send_string(f"{topic} {json.dumps(payload, ensure_ascii=False)}")
    except Exception:
        pass
# --- end helper ---

# --- LCD (opcjonalnie) ---
DISABLE_LCD = os.getenv("DISABLE_LCD", "0") == "1"
NO_DRAW = os.getenv("NO_DRAW", "0") == "1"

def _lcd_init():
    if DISABLE_LCD:
        return None
    # import klasy niezależnie od struktury pakietu
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

    t0 = time.time()
    frames = 0

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

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = haar.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30,30))

        if not NO_DRAW:
            for (x,y,w,h) in faces:
                cv2.rectangle(frame, (x,y), (x+w,y+h), (0,255,0), 2)

        # publikacja vision.face tylko gdy są twarze (debounce/out TTL zrobi dispatcher)
        if len(faces) > 0:
            pub("vision.face", {"present": True, "score": 0.9, "count": int(len(faces))})

        lcd_show_bgr(frame)

        frames += 1
        if frames % 60 == 0:
            dt = time.time() - t0
            fps = frames/dt if dt > 0 else 0.0
            print(f"[takeover] fps={fps:.1f}", flush=True)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
