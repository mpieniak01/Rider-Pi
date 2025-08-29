#!/usr/bin/env python3
"""
Rider-Pi: podgląd kamery na 2" SPI LCD + (opcjonalnie) prosta detekcja twarzy.

Zainspirowane rozwiązaniem producenta (OpenCV + PIL + LCD_2inch):
  - capture: cv2.VideoCapture(0), niska rozdzielczość 320x240, MJPG
  - render: BGR->RGB -> PIL.Image -> display.ShowImage(...)
  - (opcjonalnie) detekcja: Haar Cascade co N klatek

ENV:
  VISION_HUMAN=1            włącz detekcję twarzy (domyślnie 0)
  VISION_FACE_EVERY=5       co ile klatek liczyć detekcję (domyślnie 5)
  PREVIEW_ROT=0|90|180|270  rotacja obrazu przed wyświetleniem (domyślnie 0)

Użycie:
  sudo python3 -u apps/camera/preview_lcd.py           # podgląd
  sudo VISION_HUMAN=1 PREVIEW_ROT=270 python3 -u apps/camera/preview_lcd.py

Zakończenie: Ctrl+C – skrypt spróbuje wyłączyć ekran (scripts/lcdctl.py off).
"""
from __future__ import annotations
import os, sys, time, signal

try:
    import cv2
except Exception as e:
    print("[preview] Brak OpenCV: sudo apt-get install -y python3-opencv", e, file=sys.stderr)
    sys.exit(1)

try:
    import xgoscreen.LCD_2inch as LCD_2inch
except Exception as e:
    print("[preview] Brak modułu xgoscreen.LCD_2inch (biblioteka producenta)", e, file=sys.stderr)
    sys.exit(1)

from PIL import Image

HUMAN_EN   = int(os.getenv("VISION_HUMAN", "0"))
FACE_EVERY = max(1, int(os.getenv("VISION_FACE_EVERY", "5")))
ROT        = int(os.getenv("PREVIEW_ROT", "0"))  # 0/90/180/270


def bgr_to_pil(img):
    # OpenCV = BGR, PIL = RGB
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    im = Image.fromarray(img_rgb)
    if ROT in (90, 180, 270):
        im = im.rotate(ROT, expand=False)
    return im


def main():
    # LCD init
    disp = LCD_2inch.LCD_2inch()
    try:
        disp.Init()
    except Exception:
        # starsze biblioteki nie mają Init()
        pass
    disp.clear()

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

    # (opcjonalnie) detektor twarzy
    face_cascade = None
    if HUMAN_EN:
        try:
            face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        except Exception:
            face_cascade = None

    fidx = 0
    t0 = time.time(); frames = 0

    print("[preview] Start. Ctrl+C aby zakończyć.")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.02)
                continue

            if face_cascade is not None and (fidx % FACE_EVERY == 0):
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=3, minSize=(40, 40))
                for (x, y, w, h) in faces:
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

            fidx += 1; frames += 1
            if frames % 10 == 0:
                fps = frames / max(1e-6, (time.time() - t0))
                cv2.putText(frame, f"{fps:.1f} fps", (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)

            disp.ShowImage(bgr_to_pil(frame))

    except KeyboardInterrupt:
        pass
    finally:
        try:
            cap.release()
        except Exception:
            pass
        # zgaś LCD po wyjściu (best-effort)
        try:
            os.system("sudo -n python3 scripts/lcdctl.py off >/dev/null 2>&1 || sudo python3 scripts/lcdctl.py off")
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
