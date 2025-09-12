#!/usr/bin/env python3
# Preview + MobileNet-SSD (Caffe) — zapis RAW/PROC do /home/pi/robot/snapshots (atomowo)
# + ramki na LCD, + heartbeat, + publikacja vision.person (tylko przy realnym trafieniu)
import json
import os
import time
from typing import List, Optional, Set, Tuple

import cv2
import numpy as np

from common.bus import BusPub
from common.cam_heartbeat import CameraHB
from common.snap import Snapper
from apps.camera.utils import env_flag, open_camera

PUB = BusPub()
HB  = CameraHB(mode="ssd")

# --- ścieżki / env ---
# akceptuj obie nazwy (SNAP_DIR i SNAP_BASE) by uniknąć rozjazdów z usługą/API
SNAP_DIR = os.getenv("SNAP_DIR") or os.getenv("SNAP_BASE") or "/home/pi/robot/snapshots"
os.makedirs(SNAP_DIR, exist_ok=True)
SNAP = Snapper(base_dir=SNAP_DIR)

ROT = int(os.getenv("PREVIEW_ROT", "270"))
FLIP_H = env_flag("PREVIEW_FLIP_H", False)
FLIP_V = env_flag("PREVIEW_FLIP_V", False)
DISABLE_LCD = env_flag("DISABLE_LCD", False)
NO_DRAW = env_flag("NO_DRAW", False)

# możliwość wymuszenia rozszerzenia snapshotów
SNAP_EXT_FORCED = (os.getenv("SNAP_EXT","").strip().lower() or None)  # ".jpg" | ".png" | ".bmp"

# --- anty-migotanie + throttling WWW ---
# Trzymamy ostatnie trafienia przez DRAW_LATCH_MS (ms) do rysowania (nie do publikacji!)
DRAW_LATCH_MS  = int(os.getenv("DRAW_LATCH_MS", "700"))
# Nie zapisujemy proc/raw częściej niż co SNAP_EVERY_MS (zmniejsza I/O i lag w WWW)
SNAP_EVERY_MS  = int(os.getenv("SNAP_EVERY_MS", "500"))

_last_dets: List[Tuple[str, float, Tuple[int,int,int,int]]] = []
_last_det_ts_ms: float = 0.0
_next_snap_ts_ms: float = 0.0

def _now_ms() -> float:
    return time.time() * 1000.0

def latch_dets(dets_now: List[Tuple[str,float,Tuple[int,int,int,int]]]
               ) -> List[Tuple[str,float,Tuple[int,int,int,int]]]:
    """Utrzymuje ostatnie bboxy przez DRAW_LATCH_MS, żeby obraz nie mrugał."""
    global _last_dets, _last_det_ts_ms
    t = _now_ms()
    if dets_now:
        _last_dets = dets_now
        _last_det_ts_ms = t
        return dets_now
    if _last_dets and (t - _last_det_ts_ms) < DRAW_LATCH_MS:
        return _last_dets
    return dets_now

def should_snap_now() -> bool:
    """Kontrola częstotliwości zapisu snapshotów dla WWW."""
    global _next_snap_ts_ms
    t = _now_ms()
    if t >= _next_snap_ts_ms:
        _next_snap_ts_ms = t + SNAP_EVERY_MS
        return True
    return False

def apply_rotation(frame, rot, flip_h, flip_v):
    if rot in (90,180,270):
        k = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}[rot]
        frame = cv2.rotate(frame, k)
    if flip_h: frame = cv2.flip(frame, 1)
    if flip_v: frame = cv2.flip(frame, 0)
    return frame

def _lcd_init():
    if DISABLE_LCD: return None
    try:
        from xgoscreen.LCD_2inch import LCD_2inch
        lcd = LCD_2inch(); lcd.rotation = 0
        return lcd
    except Exception:
        return None
_LCD = _lcd_init()

def lcd_show_bgr(img_bgr):
    if _LCD is None or NO_DRAW: return
    try:
        from PIL import Image
        img = cv2.resize(img_bgr, (320,240), interpolation=cv2.INTER_LINEAR)
        _LCD.ShowImage(Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
    except Exception:
        pass

# Kamera (Picamera2 → V4L2 fallback) w utils.open_camera

CLASSES = ["background","aeroplane","bicycle","bird","boat","bottle","bus","car","cat",
           "chair","cow","diningtable","dog","horse","motorbike","person","pottedplant",
           "sheep","sofa","train","tvmonitor"]

def load_ssd():
    proto = os.path.join("models","ssd","MobileNetSSD_deploy.prototxt")
    model = os.path.join("models","ssd","MobileNetSSD_deploy.caffemodel")
    if not (os.path.isfile(proto) and os.path.isfile(model)):
        raise FileNotFoundError("Brak modeli SSD w models/ssd/")
    if os.path.getsize(model) < 5_000_000:
        raise IOError(f"Uszkodzony/niepełny model Caffe (size={os.path.getsize(model)} B) – potrzebny ~23MB.")
    return cv2.dnn.readNetFromCaffe(proto, model)

def parse_classes_env() -> Set[str]:
    raw = os.getenv("SSD_CLASSES","person")
    raw = "*" if (raw is None) else raw
    s = {x.strip().lower() for x in raw.split(",") if x.strip()}
    return set() if ("*" in s or "all" in s) else s

# ---------- snapshot encode helpers (JPG→PNG→BMP, atomowo) ----------
_SELECTED_EXT: Optional[str] = None

def _try_encode(ext: str, img, params) -> Optional[bytes]:
    try:
        ok, buf = cv2.imencode(ext, img, params)
        if ok: return buf.tobytes()
    except Exception:
        pass
    return None

def _select_ext(img_raw, img_proc) -> str:
    if SNAP_EXT_FORCED in (".jpg",".jpeg",".png",".bmp"):
        table = {
            ".jpg":[int(cv2.IMWRITE_JPEG_QUALITY),85],
            ".jpeg":[int(cv2.IMWRITE_JPEG_QUALITY),85],
            ".png":[int(cv2.IMWRITE_PNG_COMPRESSION),3],
            ".bmp":[]
        }
        p = table[".jpg"] if SNAP_EXT_FORCED==".jpeg" else table[SNAP_EXT_FORCED]
        if _try_encode(SNAP_EXT_FORCED, img_raw, p) and _try_encode(SNAP_EXT_FORCED, img_proc, p):
            return ".jpg" if SNAP_EXT_FORCED==".jpeg" else SNAP_EXT_FORCED
    for ext, params in [(".jpg",[int(cv2.IMWRITE_JPEG_QUALITY),85]),
                        (".png",[int(cv2.IMWRITE_PNG_COMPRESSION),3]),
                        (".bmp",[])]:
        if _try_encode(ext, img_raw, params) and _try_encode(ext, img_proc, params):
            return ext
    return ".bmp"

def _atomic_write_bytes(path: str, data: bytes):
    tmp = path + ".tmp"
    try:
        with open(tmp,"wb") as f: f.write(data)
        os.replace(tmp, path)
        return True
    except Exception:
        try: os.remove(tmp)
        except Exception: pass
        return False

def save_raw_and_proc(raw_img, proc_img):
    """Zapisz oba pliki w tym samym działającym formacie (auto-wybór przy 1. zapisie)."""
    global _SELECTED_EXT
    if _SELECTED_EXT is None:
        _SELECTED_EXT = _select_ext(raw_img, proc_img)
        print(f"[snap] snapshot ext = {_SELECTED_EXT}", flush=True)
    params = {
        ".jpg":[int(cv2.IMWRITE_JPEG_QUALITY),85],
        ".png":[int(cv2.IMWRITE_PNG_COMPRESSION),3],
        ".bmp":[]
    }[_SELECTED_EXT]
    ext = _SELECTED_EXT

    # zakoduj w pamięci i zapisz atomowo
    for name, img in (("raw",raw_img), ("proc",proc_img)):
        data = _try_encode(ext, img, params)
        if data is None:
            # awaryjnie dobierz ponownie
            _SELECTED_EXT = _select_ext(raw_img, proc_img)
            print(f"[snap] reselect ext = {_SELECTED_EXT}", flush=True)
            ext = _SELECTED_EXT
            params = {
                ".jpg":[int(cv2.IMWRITE_JPEG_QUALITY),85],
                ".png":[int(cv2.IMWRITE_PNG_COMPRESSION),3],
                ".bmp":[]
            }[ext]
            data = _try_encode(ext, img, params)
        if data is not None:
            _atomic_write_bytes(os.path.join(SNAP_DIR, f"{name}{ext}"), data)

def main():
    SCORE = float(os.getenv("SSD_SCORE","0.55"))
    # WSPARCIE dla obu nazw: najpierw EVERY, potem SSD_EVERY (domyślnie 1 = co klatkę)
    EVERY = int(os.getenv("EVERY", os.getenv("SSD_EVERY","1")))
    CLW   = parse_classes_env()

    read, _ = open_camera((320,240))
    net = load_ssd()

    fps_ema, prev_t = None, time.time()
    frame_id, t0, frames = 0, time.time(), 0

    print(f"[ssd] start | SNAP_DIR={SNAP_DIR} | ROT={ROT} FLIP_H={FLIP_H} FLIP_V={FLIP_V} | "
          f"NO_DRAW={NO_DRAW} DISABLE_LCD={DISABLE_LCD} | SCORE>={SCORE} EVERY={EVERY} | SSD_CLASSES={'ALL' if not CLW else ','.join(sorted(CLW))}", flush=True)

    HB.tick(None, 0.0, presenting=not NO_DRAW)
    last_snap_log = time.time()

    while True:
        ok, frame = read()
        if not ok:
            time.sleep(0.01); continue

        frame = apply_rotation(frame, ROT, FLIP_H, FLIP_V)

        now = time.time()
        dt = max(1e-6, now - prev_t); inst = 1.0/dt
        fps_ema = inst if fps_ema is None else 0.9*fps_ema + 0.1*inst
        prev_t = now

        out = frame.copy()
        detections: List[Tuple[str,float,Tuple[int,int,int,int]]] = []
        fresh_detections: List[Tuple[str,float,Tuple[int,int,int,int]]] = []

        # Inference co N-tą klatkę
        if frame_id % max(1, EVERY) == 0:
            blob = cv2.dnn.blobFromImage(cv2.resize(frame,(300,300)),
                                         0.007843,(300,300),127.5,swapRB=True,crop=False)
            net.setInput(blob)
            det = net.forward()
            h, w = frame.shape[:2]
            for i in range(det.shape[2]):
                conf = float(det[0,0,i,2])
                if conf < SCORE: continue
                cls_id = int(det[0,0,i,1])
                x1 = int(det[0,0,i,3]*w); y1 = int(det[0,0,i,4]*h)
                x2 = int(det[0,0,i,5]*w); y2 = int(det[0,0,i,6]*h)
                x1 = max(0,min(x1,w-1)); y1 = max(0,min(y1,h-1))
                x2 = max(0,min(x2,w-1)); y2 = max(0,min(y2,h-1))
                if x2<=x1 or y2<=y1: continue
                name = CLASSES[cls_id] if 0<=cls_id<len(CLASSES) else str(cls_id)
                if CLW and (name.lower() not in CLW): continue
                tup = (name, conf, (x1,y1,x2,y2))
                fresh_detections.append(tup)

        # Rysowanie z LATCH (ciągły obrys dla oka)
        detections = latch_dets(fresh_detections)

        for name, conf, (x1,y1,x2,y2) in detections:
            if not NO_DRAW:
                cv2.rectangle(out,(x1,y1),(x2,y2),(0,255,255),2)
                cv2.putText(out, f"{name}:{conf:.2f}", (x1,max(0,y1-5)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,255),1,cv2.LINE_AA)

        # Publikacja tylko dla realnych trafień z tej klatki (nie latched)
        for name, conf, (x1,y1,x2,y2) in fresh_detections:
            if name.lower()=="person":
                try:
                    PUB.publish("vision.person", {
                        "present": True, "score": float(conf),
                        "bbox": [int(x1),int(y1),int(x2-x1),int(y2-y1)]
                    }, add_ts=True)
                except Exception:
                    pass

        # --- snapshoty (atomowo, z fallbackiem formatu) z throttlingiem do WWW ---
        if should_snap_now():
            save_raw_and_proc(frame, out)
            try:
                SNAP.cam(frame); SNAP.proc(out); SNAP.lcd_from_frame(out); SNAP.lcd_from_fb()
            except Exception:
                pass

        # co ~10 s lekki log diagnostyczny
        if now - last_snap_log > 10:
            try:
                for base in ("proc","raw"):
                    for ext in (".jpg",".png",".bmp"):
                        p = os.path.join(SNAP_DIR, f"{base}{ext}")
                        if os.path.exists(p):
                            s = os.path.getsize(p)
                            print(f"[snap] {base}{ext} size={s}B @ {time.strftime('%H:%M:%S')}", flush=True)
                            break
            except Exception:
                pass
            last_snap_log = now

        # LCD
        lcd_show_bgr(out)
        HB.tick(out, fps_ema, presenting=not NO_DRAW)

        frame_id += 1; frames += 1
        if frames % 60 == 0:
            dt_all = time.time() - t0
            fps = frames/dt_all if dt_all>0 else 0.0
            print(f"[ssd] fps={fps:.1f} (every={EVERY}, score>={SCORE})", flush=True)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: pass
