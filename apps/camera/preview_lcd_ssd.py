#!/usr/bin/env python3
# apps/camera/preview_lcd_ssd.py
# Preview + MobileNet-SSD (Caffe). Publikuje vision.person dla wykryć „person”.
# + wysyła camera.heartbeat (w,h,mode,fps,lcd.{active,presenting,rot})

import os, time, json
from typing import Tuple, List, Set
import numpy as np
import cv2

# --- BUS (multipart PUB) ---
from common.bus import BusPub, now_ts
from common.cam_heartbeat import CameraHB  # wspólny emiter heartbeatów

PUB = BusPub()
HB  = CameraHB(mode="ssd")

def pub(topic: str, payload: dict, add_ts: bool = False):
    """Wyślij wiadomość na bus (multipart [topic,json])."""
    try:
        PUB.publish(topic, payload, add_ts=add_ts)
    except Exception:
        pass

# --- LCD (opcjonalnie) ---
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

# --- Kamera ---
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

# --- SSD model ---
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
    CLW   = parse_classes_env()  # whitelist nazw (np. {"pe
