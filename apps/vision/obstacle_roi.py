import os, time, json, sys, cv2, numpy as np

SNAP_DIR = os.environ.get("SNAP_DIR", "/home/pi/robot/snapshots")
PROC_PATH = os.environ.get("PROC_PATH", os.path.join(SNAP_DIR, "proc.jpg"))
RAW_PATH  = os.environ.get("RAW_PATH",  os.path.join(SNAP_DIR, "raw.jpg"))
ROI_Y0 = float(os.environ.get("ROI_Y0", "0.60"))
ROI_H  = float(os.environ.get("ROI_H",  "0.35"))
EDGE_AREA_PCT = float(os.environ.get("EDGE_AREA_PCT", "0.05"))
EDGE_PIX_MIN  = int(os.environ.get("EDGE_PIX_MIN", "4000"))
PUBLISH = os.environ.get("PUBLISH", "1") == "1"
BUS_PUB = os.environ.get("BUS_PUB", "tcp://127.0.0.1:5555")
TOPIC   = os.environ.get("TOPIC", "vision.obstacle")
OUT_JSON = os.path.join(os.path.dirname(SNAP_DIR), "data", "obstacle.json")

# ZMQ (opcjonalnie)
pub = None
if PUBLISH:
    try:
        import zmq
        ctx = zmq.Context.instance()
        pub = ctx.socket(zmq.PUB)
        pub.connect(BUS_PUB)
    except Exception as e:
        print(f"[obst] warn: zmq disabled ({e})", flush=True)
        pub = None

os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)

def load_gray(path):
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    return img

def ensure_edges():
    # preferuj gotowe krawędzie z PROC
    img = load_gray(PROC_PATH)
    if img is not None:
        return img
    # fallback: z RAW wylicz Canny
    raw = load_gray(RAW_PATH)
    if raw is None:
        return None
    # lekka filtracja + Canny
    blur = cv2.GaussianBlur(raw, (3,3), 0)
    edges = cv2.Canny(blur, 60, 120)
    return edges

def roi_slice(img):
    h, w = img.shape[:2]
    y0 = int(max(0, min(1, ROI_Y0)) * h)
    hh = int(max(0.05, min(1-ROI_Y0, ROI_H)) * h)
    y1 = min(h, y0 + hh)
    return img[y0:y1, :], (w, h, y0, y1)

def decide(mask):
    nz = int(np.count_nonzero(mask))
    total = mask.size
    pct = nz / max(1, total)
    present = (pct >= EDGE_AREA_PCT) or (nz >= EDGE_PIX_MIN)
    conf = float(min(1.0, max(pct / max(1e-6, EDGE_AREA_PCT), nz / max(1, EDGE_PIX_MIN)) * 0.5))
    return present, pct, nz, total, conf

def publish(topic, obj):
    if pub is not None:
        try:
            msg = f"{topic} {json.dumps(obj, separators=(',',':'))}"
            pub.send_string(msg)
        except Exception as e:
            print(f"[obst] warn: zmq send failed: {e}", flush=True)

last_mtime = 0.0
print(f"[obst] start | SNAP_DIR={SNAP_DIR} | PROC={PROC_PATH} | ROI_Y0={ROI_Y0} ROI_H={ROI_H} | THR pct={EDGE_AREA_PCT} pix={EDGE_PIX_MIN}", flush=True)

try:
    while True:
        try:
            st = os.stat(PROC_PATH)
            m = st.st_mtime
        except FileNotFoundError:
            m = 0.0
        if m <= last_mtime:
            time.sleep(0.2)
            continue
        last_mtime = m

        edges = ensure_edges()
        if edges is None:
            print("[obst] warn: no frame yet", flush=True)
            time.sleep(0.3)
            continue

        roi, (w, h, y0, y1) = roi_slice(edges)
        present, pct, nz, total, conf = decide(roi)

        payload = {
            "type":"obstacle",
            "present": bool(present),
            "confidence": round(conf, 3),
            "edge_pct": round(pct, 4),
            "edge_nz": nz,
            "roi": {"y0": y0, "y1": y1, "w": w, "h": h},
            "ts": time.time()
        }

        # JSON obok — łatwy podgląd / integracja
        try:
            with open(OUT_JSON, "w") as f:
                json.dump(payload, f)
        except Exception as e:
            print(f"[obst] warn: write json failed: {e}", flush=True)

        publish(TOPIC, payload)
        print(f"[obst] snap present={present} pct={pct:.3f} nz={nz} roi=({y0}:{y1}/{h})", flush=True)

except KeyboardInterrupt:
    pass
finally:
    print("[obst] stop", flush=True)
