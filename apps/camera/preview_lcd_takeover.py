#!/usr/bin/env python3
"""
Rider‑Pi — Camera preview to 2" SPI LCD (takeover)

- Przejmuje LCD producenta (xgoscreen.LCD_2inch), renderuje klatki z kamery
- Wspiera dwa backendy kamery: V4L2 (UVC) i Picamera2/libcamera (CSI)
- Zabezpieczenie: lock, by tylko jedna instancja rysowała na LCD
- Na wyjściu zawsze podaje do sterownika obraz PIL 320x240 RGB
- **NEW**: bezpieczne sprzątanie przy SIGINT/SIGTERM (czarny frame + OFF)

Uruchomienie (ręcznie):
  SKIP_V4L2=1 PREVIEW_ROT=270 PREVIEW_WARMUP=12 python3 -m apps.camera

Zmienne środowiskowe:
  PREVIEW_ROT          0|90|180|270   – rotacja programowa (domyślnie 0)
  PREVIEW_WARMUP       int            – liczba klatek/wczytań na rozgrzewkę (12)
  PREVIEW_BORDER       0/1            – czerwona ramka debug (1)
  PREVIEW_ALPHA        float          – jasność (1.0)
  PREVIEW_BETA         float          – przesunięcie (0.0)
  CAMERA_IDX           int            – indeks V4L2; -1 = auto‑scan (domyślnie -1)
  SKIP_V4L2            0/1            – pomiń V4L2 i wymuś Picamera2 (0)
  VISION_HUMAN         0/1            – włącz detekcję twarzy (0)
  VISION_FACE_EVERY    int            – co ile klatek sprawdzać twarz (5)

Zachowanie przy braku kamery: animowany pattern testowy + czarne wygaszenie na wyjściu.
"""
from __future__ import annotations
import os, sys, time, subprocess, fcntl, signal

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

from PIL import Image
import numpy as np
import cv2

# ——— ENV ————————————————————————————————————————————————————————————————
ROT         = int(os.getenv("PREVIEW_ROT", "0"))            # 0/90/180/270
WARMUP_N    = max(0, int(os.getenv("PREVIEW_WARMUP", "12")))
BORDER_DBG  = int(os.getenv("PREVIEW_BORDER", "1")) != 0
ALPHA       = float(os.getenv("PREVIEW_ALPHA", "1.0"))
BETA        = float(os.getenv("PREVIEW_BETA",  "0.0"))
CAM_IDX_ENV = int(os.getenv("CAMERA_IDX", "-1"))            # -1 = auto
SKIP_V4L2   = int(os.getenv("SKIP_V4L2", "0")) != 0         # wymuś Picamera2
HUMAN_EN    = int(os.getenv("VISION_HUMAN", "0"))
FACE_EVERY  = max(1, int(os.getenv("VISION_FACE_EVERY", "5")))

# Sterownik wymaga zawsze obrazu 320x240 RGB
LCD_TW, LCD_TH = 320, 240
LOCK_PATH = "/tmp/rider_spi_lcd.lock"

# ——— sygnały i stop-flag ———————————————————————————————————————————————
STOP = False

def _sig_handler(signum, frame):
    # wymuś wyjście z pętli i przejście do finally
    global STOP
    STOP = True
    raise KeyboardInterrupt

signal.signal(signal.SIGINT, _sig_handler)
signal.signal(signal.SIGTERM, _sig_handler)

# ——— helpers —————————————————————————————————————————————————————————————

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
        print("[preview] inna instancja już rysuje (lock in use) – kończę.", file=sys.stderr)
        sys.exit(0)
    return fd


def to_panel(pil_im: Image.Image) -> Image.Image:
    """Dopasuj obraz do dokładnie 320x240 RGB, z programową rotacją."""
    im = pil_im
    if ROT in (90, 180, 270):
        im = im.rotate(ROT, expand=True)
    if im.size != (LCD_TW, LCD_TH):
        im = im.resize((LCD_TW, LCD_TH), Image.BILINEAR)
    return im


def black_frame() -> Image.Image:
    return Image.new("RGB", (LCD_TW, LCD_TH), (0, 0, 0))


def try_open_v4l2():
    """Szybki skan kilku sensownych /dev/video*, zwraca (idx, cap) albo None."""
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
    for _ in range(WARMUP_N):
        try:
            picam.capture_array()
        except Exception:
            time.sleep(0.02)
    return picam


# ——— main ———————————————————————————————————————————————————————————————

def main() -> int:
    # Jedna instancja
    _lk = acquire_lock()

    # LCD init jak u producenta
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
    backend = None
    picam = None

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
                run("sudo -n python3 scripts/lcdctl.py off >/dev/null 2>&1 || sudo python3 scripts/lcdctl.py off")
                try:
                    os.close(_lk)
                    os.unlink(LOCK_PATH)
                except Exception:
                    pass
            return 0
        backend = "picamera2"

    # Detektor twarzy (opcjonalny)
    face = None
    if HUMAN_EN:
        try:
            face = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        except Exception:
            face = None

    print(f"[preview] Start ({backend}). Ctrl+C aby zakończyć.")
    frames = 0
    t0 = time.time()
    fidx = 0

    try:
        while not STOP:
            if cap is not None:
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.01)
                    continue
                if ALPHA != 1.0 or BETA != 0.0:
                    frame = cv2.convertScaleAbs(frame, alpha=ALPHA, beta=BETA)
                if BORDER_DBG:
                    cv2.rectangle(frame, (0, 0), (frame.shape[1] - 1, frame.shape[0] - 1), (0, 0, 255), 1)
                if face is not None and (fidx % FACE_EVERY == 0):
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    for (x, y, w, h) in face.detectMultiScale(gray, 1.2, 3, minSize=(40, 40)):
                        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                im = Image.fromarray(rgb)
            else:
                arr = picam.capture_array()  # RGB888 (H,W,3)
                if BORDER_DBG:
                    arr[0:2, :, :] = [255, 0, 0]
                    arr[-2:, :, :] = [255, 0, 0]
                    arr[:, 0:2, :] = [255, 0, 0]
                    arr[:, -2:, :] = [255, 0, 0]
                if face is not None and (fidx % FACE_EVERY == 0):
                    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
                    for (x, y, w, h) in face.detectMultiScale(gray, 1.2, 3, minSize=(40, 40)):
                        cv2.rectangle(arr, (x, y), (x + w, y + h), (0, 255, 0), 2)
                im = Image.fromarray(arr)

            fidx += 1
            disp.ShowImage(to_panel(im))
            frames += 1
            time.sleep(0.001)  # łagodniejsze czasy SPI
    except KeyboardInterrupt:
        pass
    finally:
        # Zwolnij lock
        try:
            os.close(_lk)
            os.unlink(LOCK_PATH)
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
        run("sudo -n python3 scripts/lcdctl.py off >/dev/null 2>&1 || sudo python3 scripts/lcdctl.py off")
    return 0


if __name__ == "__main__":
    sys.exit(main())