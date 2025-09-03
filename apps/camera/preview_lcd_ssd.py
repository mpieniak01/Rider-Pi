#!/usr/bin/env python3
# Preview + MobileNet-SSD (Caffe) — zapis RAW/PROC do /home/pi/robot/snapshots (atomowo)
# + ramki na LCD, + heartbeat, + publikacja vision.person
import os, time
from typing import Set, Tuple, List
import cv2, numpy as np
from common.bus import BusPub
from common.cam_heartbeat import CameraHB
from common.snap import Snapper

PUB = BusPub()
HB  = CameraHB(mode="ssd")

SNAP_DIR = os.getenv("SNAP_BASE", "/home/pi/robot/snapshots")
os.makedirs(SNAP_DIR, exist_ok=True)
SNAP = Snapper(base_dir=SNAP_DIR)

def _env_flag(n, d=False): return str(os.getenv(n, str(int(d)))).lower() in ("1","true","yes","y","on")
ROT   = int(os.getenv("PREVIEW_ROT", "270"))
FLIP_H = _env_flag("PREVIEW_FLIP_H", False)
FLIP_V = _env_flag("PREVIEW_FLIP_V", False)
DISABLE_LCD = _env_flag("DISABLE_LCD", False)
NO_DRAW     = _env_flag("NO_DRAW", False)

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
    if _LCD is None: return
    try:
        from PIL import Image
        img = cv2.resize(img_bgr, (320,240), interpolation=cv2.INTER_LINEAR)
        _LCD.ShowImage(Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
    except Exception:
        pass

def open_camera(size=(320,240)):
    try:
        from picamera2 import Picamera2
        picam2 = Picamera2()
        config = picam2.create_preview_configuration(main={"size": size, "format":"RGB888"})
        picam2.configure(config); picam2.start()
        def read():
            arr = picam2.capture_array()
            return True, cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        return read, size
    except Exception:
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  size[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])
        def read(): return cap.read()
        return read, size

CLASSES = ["background","aeroplane","bicycle","bird","boat","bottle","bus","car","cat",
           "chair","cow","diningtable","dog","horse","motorbike","person","pottedplant",
           "sheep","sofa","train","tvmonitor"]

def load_ssd():
    proto = os.path.join("models","ssd","MobileNetSSD_deploy.prototxt")
    model = os.path.join("models","ssd","MobileNetSSD_deploy.caffemodel")
    if not (os.path.isfile(proto) and os.path.isfile(model)):
        raise FileNotFoundError("Brak modeli SSD w models/ssd/")
    return cv2.dnn.readNetFromCaffe(proto, model)

def parse_classes_env() -> Set[str]:
    raw = os.getenv("SSD_CLASSES","person")
    return set([x.strip().lower() for x in raw.split(",") if x.strip()])

def _atomic_write_jpeg(path: str, img, quality: int=85):
    tmp = f"{path}.tmp"
    ok = cv2.imwrite(tmp, img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if ok:
        try: os.replace(tmp, path)
        except Exception: pass

def save_raw_and_proc(raw_img, proc_img, quality: int=85):
    try:
        _atomic_write_jpeg(os.path.join(SNAP_DIR, "raw.jpg"),  raw_img,  quality)
        _atomic_write_jpeg(os.path.join(SNAP_DIR, "proc.jpg"), proc_img, quality)
    except Exception:
        pass

def main():
    SCORE = float(os.getenv("SSD_SCORE","0.55"))
    EVERY = int(os.getenv("SSD_EVERY","2"))
    CLW   = parse_classes_env()

    read, _ = open_camera((320,240))
    net = load_ssd()

    fps_ema, prev_t = None, time.time()
    frame_id, t0, frames = 0, time.time(), 0

    print(f"[ssd] start | SNAP_DIR={SNAP_DIR} | ROT={ROT} FLIP_H={FLIP_H} FLIP_V={FLIP_V} | "
          f"NO_DRAW={NO_DRAW} DISABLE_LCD={DISABLE_LCD} | SCORE>={SCORE} EVERY={EVERY}", flush=True)

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
                detections.append((name, conf, (x1,y1,x2,y2)))

        for name, conf, (x1,y1,x2,y2) in detections:
            if not NO_DRAW:
                cv2.rectangle(out,(x1,y1),(x2,y2),(0,255,255),2)
                cv2.putText(out, f"{name}:{conf:.2f}", (x1,max(0,y1-5)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,255),1,cv2.LINE_AA)
            if name.lower()=="person":
                try:
                    PUB.publish("vision.person", {
                        "present": True, "score": float(conf),
                        "bbox": [int(x1),int(y1),int(x2-x1),int(y2-y1)]
                    }, add_ts=True)
                except Exception:
                    pass

        # --- zapis snapshotów (pewny) ---
        save_raw_and_proc(frame, out, quality=85)
        try:
            SNAP.cam(frame); SNAP.proc(out); SNAP.lcd_from_frame(out); SNAP.lcd_from_fb()
        except Exception:
            pass

        if now - last_snap_log > 10:
            try:
                p = os.path.join(SNAP_DIR, "proc.jpg")
                s = os.path.getsize(p) if os.path.exists(p) else -1
                print(f"[snap] wrote proc.jpg size={s}B at {time.strftime('%H:%M:%S')}", flush=True)
            except Exception:
                pass
            last_snap_log = now

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
