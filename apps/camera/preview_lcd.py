#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rider-Pi: podgląd kamery na 2" SPI LCD + (opcjonalnie) prosta detekcja twarzy.

- Zapisuje ostatnią klatkę do:    data/last_frame.jpg  (co SAVE_LAST_EVERY klatek)
- Publikuje heartbeat na busie:   camera.heartbeat
- Respektuje tryb headless:       DISABLE_LCD=1 lub NO_DRAW=1 → nie rysuje na LCD

ENV:
  VISION_HUMAN=1            włącz detekcję twarzy (domyślnie 0)
  VISION_FACE_EVERY=5       co ile klatek liczyć detekcję (domyślnie 5)
  PREVIEW_ROT=0|90|180|270  rotacja obrazu przed wyświetleniem (domyślnie 0)
  SAVE_LAST_EVERY=10        co ile klatek zapisać last_frame.jpg (domyślnie 10)
  DISABLE_LCD=0|1           nie używaj LCD (energooszczędnie)
  NO_DRAW=0|1               nie wywołuj ShowImage (nawet jeśli LCD jest)
  BUS_PUB_PORT=5555         port PUB do brokera ZMQ (XSUB)

Użycie:
  sudo python3 -u apps/camera/preview_lcd.py
  sudo VISION_HUMAN=1 PREVIEW_ROT=270 python3 -u apps/camera/preview_lcd.py
"""

from __future__ import annotations
import os, sys, time
from pathlib import Path

# ── ENV / ustawienia
HUMAN_EN         = int(os.getenv("VISION_HUMAN", "0"))
FACE_EVERY       = max(1, int(os.getenv("VISION_FACE_EVERY", "5")))
ROT              = int(os.getenv("PREVIEW_ROT", "0") or 0)  # 0/90/180/270
SAVE_LAST_EVERY  = max(1, int(os.getenv("SAVE_LAST_EVERY", "10")))
ENV_DISABLE_LCD  = (os.getenv("DISABLE_LCD", "0") == "1")
ENV_NO_DRAW      = (os.getenv("NO_DRAW", "0") == "1")
BUS_PUB_PORT     = int(os.getenv("BUS_PUB_PORT", "5555"))

# ── Ścieżki (repo_root/data/last_frame.jpg)
REPO_ROOT  = Path(__file__).resolve().parents[2]   # .../Rider-Pi
DATA_DIR   = REPO_ROOT / "data"
LAST_FRAME = DATA_DIR / "last_frame.jpg"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── OpenCV
try:
    import cv2
except Exception as e:
    print("[preview] Brak OpenCV: sudo apt-get install -y python3-opencv", e, file=sys.stderr)
    sys.exit(1)

# ── LCD (opcjonalnie; jeśli wyłączone, jedziemy headless)
LCD_ok = False
disp = None
if not ENV_DISABLE_LCD:
    try:
        import xgoscreen.LCD_2inch as LCD_2inch
        disp = LCD_2inch.LCD_2inch()
        try:
            disp.Init()
        except Exception:
            pass
        disp.clear()
        LCD_ok = True
    except Exception as e:
        print("[preview] LCD niedostępny lub biblioteka brakująca:", e, file=sys.stderr)
        LCD_ok = False

from PIL import Image

def rotate_bgr(img_bgr, rot_deg: int):
    if rot_deg == 90:
        return cv2.rotate(img_bgr, cv2.ROTATE_90_CLOCKWISE)
    if rot_deg == 180:
        return cv2.rotate(img_bgr, cv2.ROTATE_180)
    if rot_deg == 270:
        return cv2.rotate(img_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img_bgr

def bgr_to_pil(img_bgr):
    # OpenCV = BGR, PIL = RGB; stosujemy ROT także dla wyświetlania
    img_bgr = rotate_bgr(img_bgr, ROT)
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(img_rgb)

def save_last_frame(frame_bgr):
    """Zapisz ostatnią klatkę w orientacji zgodnej z PREVIEW_ROT."""
    try:
        img = rotate_bgr(frame_bgr, ROT)
        cv2.imwrite(str(LAST_FRAME), img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    except Exception:
        pass

# ── ZMQ (opcjonalnie)
try:
    import zmq
    _ctx = zmq.Context.instance()
    _pub = _ctx.socket(zmq.PUB)
    _pub.connect(f"tcp://127.0.0.1:{BUS_PUB_PORT}")
    ZMQ_OK = True
except Exception as e:
    print("[preview] pyzmq niedostępny (heartbeat off):", e, file=sys.stderr)
    ZMQ_OK = False
    _pub = None  # type: ignore

def hb_publish(fps: float, lcd_active: bool):
    if not ZMQ_OK or _pub is None:
        return
    try:
        payload = {
            "ts": time.time(),
            "mode": "preview",
            "fps": round(float(fps), 1),
            "lcd": {
                "active": bool(lcd_active),
                "no_draw": ENV_NO_DRAW,
                "rot": ROT,
            },
        }
        _pub.send_string(f"camera.heartbeat {os.getenv('JSON_PREFIX','')}{payload}".replace("'", '"'))
        # powyżej zamieniamy ' na ", żeby nie łamać czytników JSON po stronie API
    except Exception:
        pass

def main():
    # Kamera
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
    try:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    except Exception:
        pass

    if not cap.isOpened():
        print("[preview] Kamera nie otwarta (VideoCapture(0))", file=sys.stderr)
        return 1

    # (opcjonalnie) detektor twarzy (lekki HAAR)
    face_cascade = None
    if HUMAN_EN:
        try:
            face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        except Exception:
            face_cascade = None

    frames = 0
    t0 = time.time()
    t_hb_last = 0.0

    print(f"[preview] Start. LCD={'ON' if (LCD_ok and not ENV_NO_DRAW) else 'OFF (headless)'}; ROT={ROT}°; SAVE_LAST_EVERY={SAVE_LAST_EVERY}", flush=True)
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.02)
                continue

            # (opcjonalnie) Haar co FACE_EVERY klatek
            if face_cascade is not None and (frames % FACE_EVERY == 0):
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=3, minSize=(40, 40))
                for (x, y, w, h) in faces:
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

            frames += 1

            # FPS + overlay co 10 klatek (overlay tylko jeśli rysujemy)
            elapsed = max(1e-6, (time.time() - t0))
            fps = frames / elapsed
            if LCD_ok and not ENV_NO_DRAW and (frames % 10 == 0):
                cv2.putText(frame, f"{fps:.1f} fps", (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)

            # Zapis last_frame co N klatek (energooszczędnie)
            if frames % SAVE_LAST_EVERY == 0:
                save_last_frame(frame)

            # Wyświetlenie na LCD (jeśli nie wyłączone)
            if LCD_ok and not ENV_NO_DRAW:
                try:
                    disp.ShowImage(bgr_to_pil(frame))
                except Exception:
                    # sporadyczne błędy sterownika – ignorujemy
                    pass

            # Heartbeat co ~1s
            if (time.time() - t_hb_last) >= 1.0:
                hb_publish(fps=fps, lcd_active=(LCD_ok and not ENV_NO_DRAW))
                t_hb_last = time.time()

    except KeyboardInterrupt:
        pass
    finally:
        try:
            cap.release()
        except Exception:
            pass
        # zgaś LCD po wyjściu (best-effort)
        if LCD_ok:
            try:
                os.system("sudo -n python3 ops/lcdctl.py off >/dev/null 2>&1 || sudo python3 ops/lcdctl.py off")
            except Exception:
                pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
