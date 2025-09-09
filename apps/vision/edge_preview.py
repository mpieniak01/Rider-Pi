import os, time, signal, sys
import cv2
import numpy as np

SNAP_DIR = os.environ.get("SNAP_DIR", "/home/pi/robot/snapshots")
EDGE_LOW = int(os.environ.get("EDGE_LOW", "60"))
EDGE_HIGH = int(os.environ.get("EDGE_HIGH", "120"))
SNAP_EVERY_MS = int(os.environ.get("SNAP_EVERY_MS", "500"))
PREVIEW_ROT = int(os.environ.get("PREVIEW_ROT", "0"))
PREVIEW_FLIP_H = os.environ.get("PREVIEW_FLIP_H", "0") == "1"
FRAME_W = int(os.environ.get("FRAME_W", "640"))
FRAME_H = int(os.environ.get("FRAME_H", "480"))
LAST = os.environ.get("LAST_FRAME", "/home/pi/robot/data/last_frame.jpg")

RAW  = os.path.join(SNAP_DIR, "raw.jpg")
PROC = os.path.join(SNAP_DIR, "proc.jpg")
os.makedirs(SNAP_DIR, exist_ok=True)
os.makedirs(os.path.dirname(LAST), exist_ok=True)

def rot_flip(img):
    if PREVIEW_ROT == 90:
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    elif PREVIEW_ROT == 180:
        img = cv2.rotate(img, cv2.ROTATE_180)
    elif PREVIEW_ROT == 270:
        img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if PREVIEW_FLIP_H:
        img = cv2.flip(img, 1)
    return img

def save_jpeg(path, bgr, quality=85):
    ok, enc = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        return 0
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(enc.tobytes())
    os.replace(tmp, path)
    return len(enc)

# --- Backend A: Picamera2/libcamera ---
have_p2 = False
picam = None
try:
    from picamera2 import Picamera2
    picam = Picamera2()
    cfg = picam.create_preview_configuration(main={"size": (FRAME_W, FRAME_H), "format": "RGB888"})
    picam.configure(cfg)
    picam.start()
    have_p2 = True
except Exception as e:
    picam = None
    have_p2 = False

# --- Backend B: OpenCV V4L2 ---
cap = None
def open_v4l2():
    c = cv2.VideoCapture(0, cv2.CAP_V4L2)
    c.set(cv2.CAP_PROP_FRAME_WIDTH,  FRAME_W)
    c.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
    c.set(cv2.CAP_PROP_FPS, 15)
    try: c.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception: pass
    # NIE wymuszamy MJPG (często brak wsparcia dla kamer CSI)
    return c

if not have_p2:
    cap = open_v4l2()
    if not cap.isOpened():
        print("[edge] ERROR: cannot open camera(0) via V4L2", flush=True)
        sys.exit(1)

print(f"[edge] start | backend={'Picamera2' if have_p2 else 'V4L2'} | SNAP_DIR={SNAP_DIR} "
      f"| W×H={FRAME_W}x{FRAME_H} | EDGE={EDGE_LOW}/{EDGE_HIGH} | EVERY={SNAP_EVERY_MS}ms "
      f"| ROT={PREVIEW_ROT} | FLIP_H={PREVIEW_FLIP_H}", flush=True)

running = True
def _stop(*_): 
    global running; running = False
signal.signal(signal.SIGINT, _stop)
signal.signal(signal.SIGTERM, _stop)

period = SNAP_EVERY_MS / 1000.0
next_t = time.time()
last_ok = time.time()

def get_frame():
    # Zwraca BGR lub None
    global picam, cap, have_p2
    if have_p2 and picam is not None:
        try:
            rgb = picam.capture_array()  # RGB
            if rgb is None: 
                return None
            return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        except Exception:
            return None
    else:
        if cap is None: 
            return None
        ok, frame = cap.read()
        if not ok:
            return None
        return frame

reopen_deadline = 2.0  # s bez klatek -> reopen
while running:
    frame = get_frame()
    now = time.time()

    if frame is None:
        if (now - last_ok) >= reopen_deadline:
            # reopen obu backendów w bezpieczny sposób
            if have_p2 and picam is not None:
                try: picam.stop()
                except Exception: pass
                try:
                    picam.start()
                except Exception:
                    # spróbuj całkowitego reinit
                    try:
                        from picamera2 import Picamera2
                        picam = Picamera2()
                        cfg = picam.create_preview_configuration(main={"size": (FRAME_W, FRAME_H), "format": "RGB888"})
                        picam.configure(cfg)
                        picam.start()
                    except Exception:
                        pass
            else:
                try:
                    if cap is not None: cap.release()
                except Exception:
                    pass
                time.sleep(0.2)
                cap = open_v4l2()
            print("[edge] warn: no frame ~2s, reopening camera", flush=True)
            last_ok = now  # zapobiegaj spamowi
        time.sleep(0.02)
        continue

    last_ok = now

    # RAW
    raw_bgr = rot_flip(frame)
    raw_len = save_jpeg(RAW, raw_bgr)

    # PROC (Canny)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 1.0)
    edges = cv2.Canny(blur, EDGE_LOW, EDGE_HIGH)
    edges_bgr = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
    edges_bgr = rot_flip(edges_bgr)
    proc_len = save_jpeg(PROC, edges_bgr)

    # dla dashboardu
    _ = save_jpeg(LAST, raw_bgr, quality=80)

    print(f"[snap] raw.jpg={raw_len}B proc.jpg={proc_len}B @ {time.strftime('%H:%M:%S')}", flush=True)

    next_t += period
    delay = next_t - time.time()
    if delay > 0:
        time.sleep(delay)
    else:
        next_t = time.time()

# cleanup
try:
    if have_p2 and picam is not None: picam.stop()
except Exception:
    pass
try:
    if cap is not None: cap.release()
except Exception:
    pass
print("[edge] stop", flush=True)
