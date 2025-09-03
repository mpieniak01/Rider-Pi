#!/usr/bin/env python3
# SSD preview + pewny zapis RAW/PROC do /home/pi/robot/snapshots (atomowo) + LCD
import os, time
import cv2, numpy as np

SNAP_DIR = os.getenv("SNAP_BASE", "/home/pi/robot/snapshots")
os.makedirs(SNAP_DIR, exist_ok=True)

ROT   = int(os.getenv("PREVIEW_ROT", "270"))
FLIP_H = os.getenv("PREVIEW_FLIP_H","0").lower() in ("1","true","yes","on","y")
FLIP_V = os.getenv("PREVIEW_FLIP_V","0").lower() in ("1","true","yes","on","y")
DISABLE_LCD = os.getenv("DISABLE_LCD","0").lower() in ("1","true","yes","on","y")
NO_DRAW     = os.getenv("NO_DRAW","0").lower() in ("1","true","yes","on","y")

CLASSES = ["background","aeroplane","bicycle","bird","boat","bottle","bus","car","cat",
           "chair","cow","diningtable","dog","horse","motorbike","person","pottedplant",
           "sheep","sofa","train","tvmonitor"]

def apply_rotation(frame):
    if ROT in (90,180,270):
        k = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}[ROT]
        frame = cv2.rotate(frame, k)
    if FLIP_H: frame = cv2.flip(frame, 1)
    if FLIP_V: frame = cv2.flip(frame, 0)
    return frame

def open_camera(size=(320,240)):
    try:
        from picamera2 import Picamera2
        picam2 = Picamera2()
        config = picam2.create_preview_configuration(main={"size": size, "format":"RGB888"})
        picam2.configure(config); picam2.start()
        def read():
            arr = picam2.capture_array()
            return True, cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        return read
    except Exception:
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  size[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])
        def read(): return cap.read()
        return read

def lcd_show_bgr(img_bgr):
    if DISABLE_LCD: return
    try:
        from xgoscreen.LCD_2inch import LCD_2inch
        from PIL import Image
        lcd = LCD_2inch(); lcd.rotation = 0
        img = cv2.resize(img_bgr, (320,240), interpolation=cv2.INTER_LINEAR)
        lcd.ShowImage(Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
    except Exception:
        pass

def load_ssd():
    proto = os.path.join("models","ssd","MobileNetSSD_deploy.prototxt")
    model = os.path.join("models","ssd","MobileNetSSD_deploy.caffemodel")
    if not (os.path.isfile(proto) and os.path.isfile(model)):
        print("[err] Brak modeli SSD w models/ssd/", flush=True)
        return None
    return cv2.dnn.readNetFromCaffe(proto, model)

def atomic_write(path, img, quality_jpg=85, compression_png=3):
    """Atomowy zapis z użyciem imencode – działa niezależnie od rozszerzenia TMP."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        params = [int(cv2.IMWRITE_JPEG_QUALITY), int(quality_jpg)]
        enc = ".jpg"
    elif ext == ".png":
        params = [int(cv2.IMWRITE_PNG_COMPRESSION), int(compression_png)]
        enc = ".png"
    else:
        raise ValueError(f"Nieobsługiwane rozszerzenie: {ext}")
    ok, buf = cv2.imencode(enc, img, params)
    if not ok:
        print(f"[snap] imencode FAILED for {path}", flush=True)
        return False
    tmp = path + ".tmp"  # rozszerzenie TMP już bez znaczenia – piszemy bajty
    try:
        with open(tmp, "wb") as f:
            f.write(buf.tobytes())
        os.replace(tmp, path)
        return True
    except Exception as e:
        print(f"[snap] atomic replace FAILED for {path}: {e}", flush=True)
        try:
            if os.path.exists(tmp): os.remove(tmp)
        except Exception: pass
        return False

def main():
    SCORE = float(os.getenv("SSD_SCORE","0.45"))
    EVERY = int(os.getenv("SSD_EVERY","1"))
    CLW   = set([x.strip().lower() for x in os.getenv("SSD_CLASSES","person").split(",") if x.strip()])

    read = open_camera()
    net = load_ssd()
    print(f"[start] SNAP_DIR={SNAP_DIR} ROT={ROT} LCD={'off' if DISABLE_LCD else 'on'} SCORE>={SCORE} EVERY={EVERY}", flush=True)

    frames=0
    while True:
        ok, frame = read()
        if not ok: time.sleep(0.01); continue
        frame = apply_rotation(frame)
        out = frame.copy()

        if net is not None and frames % max(1,EVERY) == 0:
            blob = cv2.dnn.blobFromImage(cv2.resize(frame,(300,300)), 0.007843,(300,300),127.5, swapRB=True, crop=False)
            net.setInput(blob); det = net.forward()
            h,w = frame.shape[:2]
            for i in range(det.shape[2]):
                conf = float(det[0,0,i,2]);  cls_id = int(det[0,0,i,1])
                if conf < SCORE: continue
                name = CLASSES[cls_id] if 0<=cls_id<len(CLASSES) else str(cls_id)
                if CLW and (name.lower() not in CLW): continue
                x1 = int(det[0,0,i,3]*w); y1 = int(det[0,0,i,4]*h)
                x2 = int(det[0,0,i,5]*w); y2 = int(det[0,0,i,6]*h)
                x1 = max(0,min(x1,w-1)); y1 = max(0,min(y1,h-1))
                x2 = max(0,min(x2,w-1)); y2 = max(0,min(y2,h-1))
                if x2<=x1 or y2<=y1: continue
                if not NO_DRAW:
                    cv2.rectangle(out,(x1,y1),(x2,y2),(0,255,255),2)
                    cv2.putText(out, f"{name}:{conf:.2f}", (x1,max(0,y1-5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,255),1,cv2.LINE_AA)

        ok_raw  = atomic_write(os.path.join(SNAP_DIR,"raw.jpg"),  frame, 85, 3)
        ok_proc = atomic_write(os.path.join(SNAP_DIR,"proc.jpg"), out,   85, 3)

        if frames % 30 == 0:
            s = os.path.getsize(os.path.join(SNAP_DIR,"proc.jpg")) if os.path.exists(os.path.join(SNAP_DIR,"proc.jpg")) else -1
            print(f"[snap] proc.jpg size={s}B  ok_raw={ok_raw} ok_proc={ok_proc}", flush=True)

        lcd_show_bgr(out)
        frames += 1

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: pass
