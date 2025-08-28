"""
ŚCIEŻKA: apps/camera/cam_motion.py
ROLA: Prosty detektor ruchu z opcjonalną detekcją twarzy (Haar Cascade).
      Publikuje stan jako JSON (stdout) lub przez ZMQ, jeśli dostępne.

ENV:
  CAM_DEV=/dev/video0|0      – urządzenie kamery (numer lub ścieżka), domyślnie 0
  FPS=15                     – docelowe FPS przetwarzania
  LORES_W=320, LORES_H=240   – rozdzielczość przetwarzania (do ruchu/twarzy)
  MOTION_THR=8.0             – próg „moving” dla metryki ruchu
  VISION_HUMAN=0/1           – włącz/wyłącz detekcję twarzy
  VISION_FACE_EVERY=5        – co ile klatek robić detekcję twarzy
  ZMQ_PUB=tcp://127.0.0.1:5556 – opcjonalny endpoint PUB; jeśli brak, drukuje na stdout

WYJŚCIE (przykład):
  {
    "ts": 1690000000.123,
    "motion": 12.3,
    "moving": true,
    "human": false,
    "size": [320, 240],
    "fps": 15.0
  }

Uruchamianie:
  python3 -m apps.camera.cam_motion
  VISION_HUMAN=1 VISION_FACE_EVERY=5 python3 -m apps.camera.cam_motion
"""
from __future__ import annotations
import os, sys, time
from typing import Optional, Tuple

# --- konfiguracja z ENV -------------------------------------------------------
def _int(env: str, default: int) -> int:
    try:
        return int(os.getenv(env, str(default)))
    except Exception:
        return default

def _float(env: str, default: float) -> float:
    try:
        return float(os.getenv(env, str(default)))
    except Exception:
        return default

CAM_DEV     = os.getenv("CAM_DEV", "0")
FPS         = _float("FPS", 15.0)
LORES_W     = _int("LORES_W", 320)
LORES_H     = _int("LORES_H", 240)
MOTION_THR  = _float("MOTION_THR", 8.0)
HUMAN_EN    = _int("VISION_HUMAN", 0)  # 1=on, 0=off
FACE_EVERY  = _int("VISION_FACE_EVERY", 5)
ZMQ_PUB_EP  = os.getenv("ZMQ_PUB", "")

# --- bezpieczny import opcjonalnych bibliotek --------------------------------
try:
    import cv2  # type: ignore
except Exception:  # brak OpenCV – moduł wciąż się skompiluje, ale run() nie ruszy
    cv2 = None  # type: ignore

try:
    import numpy as np  # type: ignore
except Exception:
    np = None  # type: ignore

try:
    import zmq  # type: ignore
except Exception:
    zmq = None  # type: ignore


# --- publikacja ----------------------------------------------------------------
class _StdoutPub:
    def send_json(self, obj):
        import json
        print(json.dumps(obj, ensure_ascii=False), flush=True)

def make_pub():
    if ZMQ_PUB_EP and zmq is not None:
        try:
            ctx = zmq.Context.instance()
            sock = ctx.socket(zmq.PUB)
            sock.bind(ZMQ_PUB_EP)
            return sock
        except Exception:
            pass
    return _StdoutPub()


def pub(sock, payload):
    try:
        sock.send_json(payload)
    except Exception:
        try:
            # stdout fallback
            _StdoutPub().send_json(payload)
        except Exception:
            pass


# --- pomocnicze ---------------------------------------------------------------

def _open_cam(dev: str):
    if cv2 is None:
        raise RuntimeError("OpenCV nie jest zainstalowany (cv2==None)")
    try:
        idx = int(dev)
        cap = cv2.VideoCapture(idx)
    except Exception:
        cap = cv2.VideoCapture(dev)
    if not cap or not cap.isOpened():
        raise RuntimeError(f"Nie mogę otworzyć kamery: {dev}")
    try:
        cap.set(cv2.CAP_PROP_FPS, FPS)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, LORES_W)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, LORES_H)
    except Exception:
        pass
    return cap


def _face_cascade_or_none():
    if not HUMAN_EN or cv2 is None:
        return None
    try:
        return cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    except Exception:
        return None


def _motion_metric(prev_gray, gray) -> float:
    # metryka: średnia wartości różnicy po lekkim rozmyciu
    if np is None or cv2 is None:
        return 0.0
    try:
        delta = cv2.absdiff(prev_gray, gray)
        blur  = cv2.GaussianBlur(delta, (9, 9), 0)
        return float(blur.mean())
    except Exception:
        return 0.0


# --- główna pętla -------------------------------------------------------------

def run() -> None:
    if cv2 is None or np is None:
        print("[cam] Brak zależności (cv2/numpy) – instalacja wymagana.", file=sys.stderr)
        return

    cap = _open_cam(CAM_DEV)
    pubsock = make_pub()

    ok, frame = cap.read()
    if not ok:
        print("[cam] Brak klatki z kamery (start)", file=sys.stderr)
        return

    frame = cv2.resize(frame, (LORES_W, LORES_H))
    prev_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    face_cascade = _face_cascade_or_none()
    fidx = 0

    t_last = time.time()
    while True:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.01)
            continue
        frame = cv2.resize(frame, (LORES_W, LORES_H))
        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        motion = _motion_metric(prev_gray, gray)
        prev_gray = gray

        human = False
        try:
            if HUMAN_EN and face_cascade is not None and (fidx % max(1, FACE_EVERY) == 0):
                # zmniejsz próg i rozmiar detekcji, by było tanio
                faces = face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=3, minSize=(40, 40))
                human = len(faces) > 0
        except Exception:
            human = False
        fidx += 1

        now = time.time()
        state = {
            "ts": now,
            "motion": motion,
            "moving": bool(motion >= MOTION_THR),
            "human": bool(human),
            "size": [LORES_W, LORES_H],
            "fps": float(FPS),
        }
        pub(pubsock, state)

        # proste taktowanie do FPS
        dt = 1.0 / max(1.0, FPS)
        t_spent = time.time() - t_last
        if t_spent < dt:
            time.sleep(dt - t_spent)
        t_last = time.time()


def main():
    try:
        run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__" or __name__ == "apps.camera.cam_motion":
    main()