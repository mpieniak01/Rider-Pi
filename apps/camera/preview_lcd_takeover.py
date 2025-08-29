#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rider-Pi — Camera preview to 2" SPI LCD (takeover) — wersja bazowa (bez TFLite)

Zachowane:
- lock 1-instancji (SPI LCD), ENV PREVIEW_*, fallback V4L2/Picamera2
- opcjonalna detekcja twarzy (HAAR) sterowana ENV
- pattern test gdy brak kamery
- bezpieczne sprzątanie (czarny frame + lcdctl off)

Uruchomienie:
  export SKIP_V4L2=1 PREVIEW_ROT=270
  python3 -u apps/camera/preview_lcd_takeover.py

ENV:
  PREVIEW_ROT          0|90|180|270   – rotacja soft (0)
  PREVIEW_WARMUP       int            – rozgrzewka (12)
  PREVIEW_BORDER       0/1            – czerwona ramka debug (1)
  PREVIEW_ALPHA        float          – wzmocnienie jasności (1.0)
  PREVIEW_BETA         float          – przesunięcie jasności (0.0)
  CAMERA_IDX           int            – indeks V4L2; -1=auto (-1)
  SKIP_V4L2            0/1            – pomiń V4L2, wymuś Picamera2 (1)
  VISION_HUMAN         0/1            – włącz detekcję twarzy (0)
  VISION_FACE_EVERY    int            – co ile klatek HAAR (5)
"""

from __future__ import annotations
import os, sys, time, subprocess, fcntl, signal
import numpy as np
from PIL import Image
import cv2

# Ścieżka projektu (dla scripts/lcdctl.py itp.)
PROJ_ROOT = "/home/pi/robot"
if PROJ_ROOT not in sys.path:
    sys.path.insert(0, PROJ_ROOT)

# Sterownik LCD producenta
try:
    import xgoscreen.LCD_2inch as LCD_2inch
except Exception as e:  # pragma: no cover
    print("[preview] Brak xgoscreen.LCD_2inch:", e, file=sys.stderr)
    sys.exit(1)

# —— ENV ————————————————————————————————————————————————————————————————
ROT         = int(os.getenv("PREVIEW_ROT", "0"))                  # 0/90/180/270
WARMUP_N    = max(0, int(os.getenv("PREVIEW_WARMUP", "12")))
BORDER_DBG  = int(os.getenv("PREVIEW_BORDER", "1")) != 0
ALPHA       = float(os.getenv("PREVIEW_ALPHA", "1.0"))
BETA        = float(os.getenv("PREVIEW_BETA",  "0.0"))
CAM_IDX_ENV = int(os.getenv("CAMERA_IDX", "-1"))                  # -1 = auto
SKIP_V4L2   = int(os.getenv("SKIP_V4L2", "1")) != 0               # domyślnie Picamera2
HUMAN_EN    = int(os.getenv("VISION_HUMAN", "0")) != 0
FACE_EVERY  = max(1, int(os.getenv("VISION_FACE_EVERY", "5")))

# Stałe LCD
LCD_TW, LCD_TH = 320, 240
LOCK_PATH = "/tmp/rider_spi_lcd.lock"

# —— sygnały i stop-flag ———————————————————————————————————————————————
STOP = False
def _sig_handler(signum, frame):
    global STOP
    STOP = True
    raise KeyboardInterrupt
signal.signal(signal.SIGINT, _sig_handler)
signal.signal(signal.SIGTERM, _sig_handler)

# —— helpers —————————————————————————————————————————————————————————————
def run(cmd: str) -> int:
    try:
        return subprocess.call(cmd, shell=True)
    except Exception:
        return 1

def acquire_lock():
    """Zezwól tylko na jedną instancję rysującą na LCD."""
    fd = os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
    except OSError:
        print("[preview] Inna instancja już rysuje (lock in use) – kończę.", file=sys.stderr)
        sys.exit(0)
    return fd

def to_panel(pil_im: Image.Image) -> Image.Image:
    """Dopasuj obraz do 320x240 RGB + programowa rotacja."""
    im = pil_im
    if ROT in (90, 180, 270):
        im = im.rotate(ROT, expand=True)
    if im.size != (LCD_TW, LCD_TH):
        im = im.resize((LCD_TW, LCD_TH), Image.BILINEAR)
    return im

def black_frame() -> Image.Image:
    return Image.new("RGB", (LCD_TW, LCD_TH), (0, 0, 0))

def try_open_v4l2():
    """Skan sensownych /dev/video*; zwraca (idx, cap) albo None."""
    def ok_frames(cap, tries=5):
        for _ in range(tries):
            r, f = cap.read()
            if r and f is not None:
                return True
            time.sleep(0.02)
        return False
    candidates = [CAM_IDX_ENV] if CAM_IDX_ENV >= 0 else [0, 1, 2, 10, 11, 12, 13, 14]
    sizes = [(320, 240), (640, 480)]
    for idx in candidates:
        cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
        if not cap.isOpened():
            continue
        for (w, h) in sizes:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            for cc in ("MJPG", "YUYV", None):
                if cc:
                    try:
                        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*cc))
                    except Exception:
                        pass
                if ok_frames(cap):
                    return idx, cap
        cap.release()
    return None

def open_picamera2():
    try:
        from picamera2 import Picamera2
    except Exception as e:
        print("[preview] Picamera2 niedostępne:", e, file=sys.stderr)
        return None
    picam = Picamera2()
    cfg = picam.create_preview_configuration(main={"size": (320, 240), "format": "RGB888"})
    picam.configure(cfg)
    picam.start()
    # rozgrzewka
    for _ in range(WARMUP_N):
        try:
            picam.capture_array()
        except Exception:
            time.sleep(0.02)
    return picam

# —— Rysowanie / HUD ————————————————————————————————————————————————
def draw_hud(frame_bgr, fps: float | None):
    if BORDER_DBG:
        cv2.rectangle(frame_bgr, (0, 0), (frame_bgr.shape[1]-1, frame_bgr.shape[0]-1), (0, 0, 255), 1)
    if fps is not None:
        cv2.putText(frame_bgr, f"FPS {fps:.1f}", (5, 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

# —— main ———————————————————————————————————————————————————————————————
def main() -> int:
    # Jedna instancja
    _lk = acquire_lock()

    # LCD init
    disp = LCD_2inch.LCD_2inch()
    try:
        disp.Init()
    except Exception:
        pass
    disp.clear()
    time.sleep(0.02)
    try:
        disp.ShowImage(black_frame())
    except Exception:
        pass

    # Wybór backendu kamery
    cap = None
    picam = None
    backend = None

    if not SKIP_V4L2:
        opened = None
        try:
            opened = try_open_v4l2()
        except Exception:
            opened = None
        if opened:
            idx, cap = opened
            backend = f"v4l2:/dev/video{idx}"

    if cap is None:
        picam = open_picamera2()
        if picam is None:
            print("[preview] Brak V4L2 i Picamera2 – pokażę pattern testowy. Ctrl+C aby zakończyć.")
            t0 = time.time()
            try:
                while not STOP:
                    t = time.time() - t0
                    arr = np.zeros((LCD_TH, LCD_TW, 3), dtype=np.uint8)
                    arr[:, :, 1] = ((np.arange(LCD_TW)[None, :] + int(t * 30)) % 255).astype(np.uint8)
                    arr[:, :, 2] = ((np.arange(LCD_TH)[:, None] + int(t * 20)) % 255).astype(np.uint8)
                    if BORDER_DBG:
                        arr[0:2, :, :] = [255, 0, 0]
                        arr[-2:, :, :] = [255, 0, 0]
                        arr[:, 0:2, :] = [255, 0, 0]
                        arr[:, -2:, :] = [255, 0, 0]
                    disp.ShowImage(to_panel(Image.fromarray(arr)))
            except KeyboardInterrupt:
                pass
            finally:
                try:
                    disp.ShowImage(black_frame())
                except Exception:
                    pass
                if os.getenv("KEEP_LCD","0") != "1":
                    run("sudo -n python3 scripts/lcdctl.py off >/dev/null 2>&1 || sudo python3 scripts/lcdctl.py off")
                try:
                    os.close(_lk); os.unlink(LOCK_PATH)
                except Exception:
                    pass
            return 0
        backend = "picamera2"

    # Opcjonalna detekcja twarzy (HAAR)
    face_cascade = None
    if HUMAN_EN:
        try:
            face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            print("[face] HAAR włączony")
        except Exception:
            face_cascade = None
            print("[face] HAAR niedostępny", file=sys.stderr)

    print(f"[preview] Start ({backend}). Ctrl+C aby zakończyć.")
    frames = 0
    t0 = time.time()
    fidx = 0

    try:
        while not STOP:
            # Pobierz ramkę jako BGR
            if cap is not None:
                ok, frame_bgr = cap.read()
                if not ok:
                    time.sleep(0.01)
                    continue
            else:
                arr_rgb = picam.capture_array()  # RGB888
                frame_bgr = cv2.cvtColor(arr_rgb, cv2.COLOR_RGB2BGR)

            # Regulacje jasności/kontrastu
            if ALPHA != 1.0 or BETA != 0.0:
                frame_bgr = cv2.convertScaleAbs(frame_bgr, alpha=ALPHA, beta=BETA)

            # Opcjonalna detekcja twarzy co N klatek
            if face_cascade is not None and (fidx % FACE_EVERY == 0):
                gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
                for (x, y, w, h) in face_cascade.detectMultiScale(gray, 1.2, 3, minSize=(40, 40)):
                    cv2.rectangle(frame_bgr, (x, y), (x + w, y + h), (0, 255, 0), 2)

            # FPS co 20 klatek
            frames += 1
            fps = None
            if frames % 20 == 0:
                fps = frames / (time.time() - t0)
                frames = 0
                t0 = time.time()
                # -> linia dla benchmarku (wypisz tylko gdy BENCH_LOG=1)
                if os.getenv("BENCH_LOG","0") == "1" and fps is not None:
                    print(f"[bench] fps={fps:.2f} mode=HAAR", flush=True)

            draw_hud(frame_bgr, fps)

            # Wyświetl
            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            disp.ShowImage(to_panel(Image.fromarray(rgb)))

            fidx += 1
            time.sleep(0.001)  # łagodne SPI
    except KeyboardInterrupt:
        pass
    finally:
        # Zwolnij lock
        try:
            os.close(_lk); os.unlink(LOCK_PATH)
        except Exception:
            pass
        # Zwolnij kamerę i zgaś LCD
        try:
            if cap is not None:
                cap.release()
        except Exception:
            pass
        try:
            if picam is not None:
                picam.stop()
        except Exception:
            pass
        try:
            disp.ShowImage(black_frame())
        except Exception:
            pass
        if os.getenv("KEEP_LCD","0") != "1":
            run("sudo -n python3 scripts/lcdctl.py off >/dev/null 2>&1 || sudo python3 scripts/lcdctl.py off")
    return 0

if __name__ == "__main__":
    sys.exit(main())
