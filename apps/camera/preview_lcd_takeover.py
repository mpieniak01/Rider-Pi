#!/usr/bin/env python3
# apps/camera/preview_lcd_takeover.py

import os
import time
import cv2
import numpy as np
from typing import Tuple
from PIL import Image

from common.bus import BusPub, now_ts
from common.cam_heartbeat import CameraHB
from common.snap import Snapper

PUB = BusPub()
HB = CameraHB(mode="haar")
SNAP = Snapper(base_dir=os.getenv("SNAP_BASE", "/home/pi/robot/snapshots"))

ROT = int(os.getenv("PREVIEW_ROT", "270"))
DISABLE_LCD = os.getenv("DISABLE_LCD", "0") == "1"
NO_DRAW     = os.getenv("NO_DRAW", "0") == "1"

LAST_FRAME_PATH = os.environ.get("LAST_FRAME_PATH", "/home/pi/robot/data/last_frame.jpg")
SAVE_EVERY      = int(os.environ.get("SAVE_EVERY", 2))

frame_counter = 0

# --- LCD init ---
def _lcd_init():
    if DISABLE_LCD:
        return None
    try:
        from xgoscreen.LCD_2inch import LCD_2inch
        lcd = LCD_2inch()
        lcd.rotation = 0
        return lcd
    except Exception:
        return None

_LCD = _lcd_init()

def lcd_show_bgr(img_bgr: np.ndarray):
    if _LCD is None:
        return
    img = cv2.resize(img_bgr, (320, 240), interpolation=cv2.INTER_LINEAR)
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    _LCD.ShowImage(Image.fromarray(img_rgb))

# --- Camera ---
def open_camera(size=(320, 240)) -> Tuple[object, Tuple[int, int]]:
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

# --- Main ---
def main():
    global frame_counter
    read, size = open_camera((320, 240))
    prev_t = time.time()
    fps_ema = None

    try:
        HB.tick(None, 0.0, presenting=not NO_DRAW)
    except Exception:
        pass

    while True:
        ok, frame = read()
        if not ok:
            time.sleep(0.01)
            continue

        now = time.time()
        dt = max(1e-6, now - prev_t)
        inst = 1.0 / dt
        fps_ema = inst if fps_ema is None else (0.9 * fps_ema + 0.1 * inst)
        prev_t = now

        out = frame.copy()
        lcd_show_bgr(out)
        HB.tick(out, fps_ema, presenting=not NO_DRAW)

        frame_counter += 1
        if frame_counter % SAVE_EVERY == 0:
            try:
                tmp = LAST_FRAME_PATH + ".tmp"
                Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB)).save(tmp, "JPEG", quality=80)
                os.replace(tmp, LAST_FRAME_PATH)
            except Exception as e:
                print(f"[save-frame] error: {e}", flush=True)

        if frame_counter % 60 == 0:
            print(f"[takeover] fps={fps_ema:.1f}", flush=True)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
