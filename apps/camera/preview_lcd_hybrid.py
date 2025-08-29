#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rider-Pi — HYBRID: person (SSD) + tracking + face (HAAR) na 2" LCD

Idea:
- Co SSD_EVERY klatek uruchamiamy MobileNet-SSD (OpenCV DNN) i wybieramy ramkę "person".
- Pomiędzy wywołaniami SSD używamy trackera (KCF/CSRT) do płynnego śledzenia.
- Wewnątrz ramki "person" co FACE_EVERY klatek sprawdzamy HAAR (twarz). Jeśli jest — rysujemy.
- Działa na Picamera2, bez TFLite. Ma BENCH_LOG i KEEP_LCD (jak pozostałe skrypty).

ENV:
  PREVIEW_ROT    = 0|90|180|270 (domyślnie 0; u Ciebie zwykle 270)
  SSD_SCORE      = 0.55         (próg detekcji SSD)
  SSD_EVERY      = 3            (co ile klatek uruchamiać SSD)
  FACE_EVERY     = 5            (co ile klatek sprawdzać twarz w ROI)
  TRACKER        = kcf|csrt     (domyślnie kcf; csrt trochę cięższy)
  SSD_PROTO      = ścieżka .prototxt (opcjonalnie)
  SSD_MODEL      = ścieżka .caffemodel (opcjonalnie)
  KEEP_LCD       = 0/1          (1 = nie gasić podświetlenia w finally)
  BENCH_LOG      = 0/1          (1 = wypisuj "[bench] fps=…")
"""

import os, time, signal, fcntl, subprocess
import cv2, numpy as np
from PIL import Image

# —— LCD / lock ——
LOCK_PATH = "/tmp/rider_spi_lcd.lock"
LCD_TW, LCD_TH = 320, 240
ROT = int(os.getenv("PREVIEW_ROT", "0"))

# —— SSD / HAAR / tracker parametry ——
SCORE      = float(os.getenv("SSD_SCORE", "0.55"))
SSD_EVERY  = max(1, int(os.getenv("SSD_EVERY", "3")))
FACE_EVERY = max(1, int(os.getenv("FACE_EVERY", "5")))
TRACKER    = os.getenv("TRACKER", "kcf").strip().lower()

PROTOTXT = os.getenv("SSD_PROTO", "models/ssd/MobileNetSSD_deploy.prototxt")
WEIGHTS  = os.getenv("SSD_MODEL", "models/ssd/MobileNetSSD_deploy.caffemodel")

CLASSES = ["background","aeroplane","bicycle","bird","boat","bottle","bus","car",
           "cat","chair","cow","diningtable","dog","horse","motorbike","person",
           "pottedplant","sheep","sofa","train","tvmonitor"]

STOP=False
def _sig(sig,frm):
    global STOP; STOP=True; raise KeyboardInterrupt
signal.signal(signal.SIGINT,_sig); signal.signal(signal.SIGTERM,_sig)

def run(cmd:str)->int:
    try: return subprocess.call(cmd, shell=True)
    except: return 1

def lock_once():
    fd = os.open(LOCK_PATH, os.O_RDWR|os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
        os.ftruncate(fd,0); os.write(fd, str(os.getpid()).encode())
    except OSError:
        print("[preview] Inna instancja rysuje LCD — kończę.", flush=True)
        raise SystemExit(0)
    return fd

def to_panel(pil_im: Image.Image)->Image.Image:
    im = pil_im.rotate(ROT, expand=True) if ROT in (90,180,270) else pil_im
    return im.resize((LCD_TW, LCD_TH), Image.BILINEAR)

def black(): return Image.new("RGB",(LCD_TW,LCD_TH),(0,0,0))

def open_cam(size=(320,240)):
    from picamera2 import Picamera2
    cam = Picamera2()
    cfg = cam.create_preview_configuration(main={"size": size, "format":"RGB888"})
    cam.configure(cfg)
    cam.start(); time.sleep(0.2)
    return cam

def load_ssd():
    if not (os.path.exists(PROTOTXT) and os.path.exists(WEIGHTS)):
        raise FileNotFoundError(f"Brak modelu SSD: {PROTOTXT} / {WEIGHTS}")
    net = cv2.dnn.readNetFromCaffe(PROTOTXT, WEIGHTS)
    try:
        net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
    except Exception:
        pass
    return net

def create_tracker(kind="kcf"):
    kind = (kind or "").lower()
    def _mk(name):
        # OpenCV różnie pakuje trackery (legacy vs nie-legacy)
        ctor = getattr(cv2, f"{name}_create", None)
        if ctor: return ctor()
        legacy = getattr(cv2, "legacy", None)
        if legacy:
            ctor = getattr(legacy, f"{name}_create", None)
            if ctor: return ctor()
        return None
    if kind == "csrt":
        t = _mk("TrackerCSRT")
        if t is not None: return t
    # fallback: KCF
    t = _mk("TrackerKCF")
    if t is not None: return t
    # ostateczny fallback: MOSSE (bardzo lekki)
    t = _mk("TrackerMOSSE")
    return t

def draw(frame, person_box, face_box, fps=None):
    if person_box is not None:
        (x1,y1,x2,y2) = person_box
        cv2.rectangle(frame,(x1,y1),(x2,y2),(0,0,255),2)
        cv2.putText(frame,"person",(x1,max(12,y1-6)),cv2.FONT_HERSHEY_SIMPLEX,0.45,(0,0,255),1)
    if face_box is not None:
        (x,y,w,h) = face_box
        cv2.rectangle(frame,(x,y),(x+w,y+h),(0,255,0),2)
        cv2.putText(frame,"face",(x,max(12,y-6)),cv2.FONT_HERSHEY_SIMPLEX,0.45,(0,255,0),1)
    if fps is not None:
        cv2.putText(frame,f"FPS {fps:.1f}",(5,14),cv2.FONT_HERSHEY_SIMPLEX,0.5,(255,255,255),1)

# lekka optymalizacja
try:
    cv2.setUseOptimized(True)
    cv2.setNumThreads(2)
except Exception:
    pass

def main():
    # LCD
    try:
        import xgoscreen.LCD_2inch as LCD_2inch
    except Exception as e:
        print("[preview] Brak xgoscreen:", e); raise SystemExit(1)
    disp = LCD_2inch.LCD_2inch()
    try: disp.Init()
    except: pass
    disp.clear(); disp.ShowImage(black())

    lk = lock_once()
    cam = None
    try:
        cam = open_cam((320,240))
        net = load_ssd()
        face_cascade = None
        try:
            face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        except Exception:
            face_cascade = None

        print("[preview] Start (HYBRID: SSD+TRACK+HAAR). Ctrl+C aby zakończyć.", flush=True)

        t0=time.time(); n=0; fps=None
        k=0
        tracker=None
        person_box=None   # (x1,y1,x2,y2) w obrazie
        face_box=None     # (x,y,w,h) w obrazie

        while not STOP:
            rgb = cam.capture_array()
            frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

            H,W = frame.shape[:2]

            # 1) tracking każdej klatki, jeśli mamy tracker
            tracked_ok=False
            if tracker is not None and person_box is not None:
                (x1,y1,x2,y2) = person_box
                # tracker używa bbox (x,y,w,h)
                init_box = (x1, y1, max(1,x2-x1), max(1,y2-y1))
                ok, bb = tracker.update(frame)
                if ok:
                    x,y,w,h = map(int, bb)
                    person_box = (max(0,x), max(0,y), min(W-1,x+w), min(H-1,y+h))
                    tracked_ok=True
                else:
                    tracker=None

            # 2) co SSD_EVERY klatek: uruchom SSD (nadpisze person_box)
            k = (k + 1) % SSD_EVERY
            if k == 0:
                blob = cv2.dnn.blobFromImage(frame, 0.007843, (300,300), 127.5)
                net.setInput(blob)
                det = net.forward()
                best = None
                best_conf = -1.0
                for i in range(det.shape[2]):
                    conf = float(det[0,0,i,2])
                    if conf < SCORE: continue
                    idx = int(det[0,0,i,1])
                    if idx != 15:     # 15 == "person" w liście CLASSES
                        continue
                    box = det[0,0,i,3:7]*[W,H,W,H]
                    x1,y1,x2,y2 = box.astype("int")
                    x1,y1 = max(0,x1), max(0,y1)
                    x2,y2 = min(W-1,x2), min(H-1,y2)
                    if conf > best_conf:
                        best_conf = conf
                        best = (x1,y1,x2,y2)
                if best is not None:
                    person_box = best
                    # reinit trackera
                    t = create_tracker(TRACKER)
                    if t is not None:
                        (x1,y1,x2,y2) = person_box
                        t.init(frame, (x1,y1,max(1,x2-x1),max(1,y2-y1)))
                        tracker = t
                    else:
                        tracker = None

            # 3) HAAR w ROI osoby co FACE_EVERY klatek
            face_box = None
            if face_cascade is not None and person_box is not None and (n % FACE_EVERY == 0):
                (x1,y1,x2,y2) = person_box
                roi = frame[y1:y2, x1:x2]
                if roi.size > 0:
                    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                    faces = face_cascade.detectMultiScale(gray, 1.1, 3, minSize=(30, 30))
                    if len(faces):
                        # bierz największą twarz
                        fx,fy,fw,fh = max(faces, key=lambda r: r[2]*r[3])
                        face_box = (x1+fx, y1+fy, fw, fh)

            # 4) FPS i bench log
            n += 1
            if n % 20 == 0:
                fps = n / (time.time() - t0); t0 = time.time(); n = 0
                if os.getenv("BENCH_LOG","0") == "1" and fps is not None:
                    print(f"[bench] fps={fps:.2f} mode=HYBRID", flush=True)

            # 5) rysowanie i LCD
            draw(frame, person_box, face_box, fps)
            out = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            disp.ShowImage(to_panel(out))
            time.sleep(0.001)

    except KeyboardInterrupt:
        pass
    finally:
        try: disp.ShowImage(black())
        except: pass
        if os.getenv("KEEP_LCD","0") != "1":
            run("sudo -n python3 scripts/lcdctl.py off >/dev/null 2>&1 || sudo python3 scripts/lcdctl.py off")
        try:
            if cam: cam.stop()
        except: pass
        try:
            os.close(lk); os.unlink(LOCK_PATH)
        except: pass

if __name__=="__main__":
    main()

