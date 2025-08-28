#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rider-Pi — LCD preview + MobileNet-SSD (OpenCV DNN)
Działa na Picamera2 i 2" LCD. Nie wymaga TFLite.

Model:
  models/ssd/MobileNetSSD_deploy.prototxt
  models/ssd/MobileNetSSD_deploy.caffemodel

ENV:
  PREVIEW_ROT    = 0|90|180|270 (domyślnie 0; u Ciebie zwykle 270)
  SSD_SCORE      = 0.5          (próg detekcji)
  SSD_PROTO      = ścieżka .prototxt (opcjonalnie)
  SSD_MODEL      = ścieżka .caffemodel (opcjonalnie)
"""
import os, time, signal, fcntl, subprocess
import cv2, numpy as np
from PIL import Image

LOCK_PATH = "/tmp/rider_spi_lcd.lock"
LCD_TW, LCD_TH = 320, 240
ROT = int(os.getenv("PREVIEW_ROT", "0"))
SCORE = float(os.getenv("SSD_SCORE", "0.5"))
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
    return net

def draw_dets(frame, dets, fps=None):
    for (x1,y1,x2,y2), label, conf in dets:
        cv2.rectangle(frame,(x1,y1),(x2,y2),(0,0,255),2)
        cv2.putText(frame,f"{label} {conf*100:.0f}%",(x1,max(12,y1-6)),
                    cv2.FONT_HERSHEY_SIMPLEX,0.45,(0,0,255),1)
    if fps is not None:
        cv2.putText(frame,f"FPS {fps:.1f}",(5,14),cv2.FONT_HERSHEY_SIMPLEX,0.5,(255,255,255),1)

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
        print("[preview] Start (Picamera2 + SSD). Ctrl+C aby zakończyć.", flush=True)

        t0=time.time(); n=0; fps=None
        while not STOP:
            rgb = cam.capture_array()                    # RGB888
            frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR) # BGR

            blob = cv2.dnn.blobFromImage(frame, 0.007843, (300,300), 127.5)
            net.setInput(blob)
            det = net.forward()

            H,W = frame.shape[:2]
            dets=[]
            for i in range(det.shape[2]):
                conf = float(det[0,0,i,2])
                if conf < SCORE: continue
                idx = int(det[0,0,i,1]); label = CLASSES[idx] if 0<=idx<len(CLASSES) else str(idx)
                box = det[0,0,i,3:7]*[W,H,W,H]
                x1,y1,x2,y2 = box.astype("int")
                dets.append(((x1,y1,x2,y2), label, conf))

            n+=1
            if n%20==0:
                fps = n/(time.time()-t0); t0=time.time(); n=0

            draw_dets(frame, dets, fps)
            out = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            disp.ShowImage(to_panel(out))
            time.sleep(0.001)
    except KeyboardInterrupt:
        pass
    finally:
        try: disp.ShowImage(black())
        except: pass
        run("sudo -n python3 scripts/lcdctl.py off >/dev/null 2>&1 || sudo python3 scripts/lcdctl.py off")
        try:
            if cam: cam.stop()
        except: pass
        try:
            os.close(lk); os.unlink(LOCK_PATH)
        except: pass

if __name__=="__main__":
    main()
