#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rider-Pi: podgląd kamery na 2" SPI LCD + (opcjonalnie) detekcja obiektów i publikacja na bus.

ZACHOWANE:
- Zapisuje ostatnią klatkę do:    data/last_frame.(jpg|png|bmp)  (pierwsza klatka od razu, dalej co SAVE_LAST_EVERY)
- Publikuje heartbeat na busie:   camera.heartbeat
- Respektuje tryb headless:       DISABLE_LCD=1 lub NO_DRAW=1 → nie rysuje na LCD
- DETECTOR=none|haar|tflite|ssd   (domyślnie none), vision.detections + vision.person
- Picamera2→V4L2 fallback

NOWE:
- Dodatkowo zapisuje RAW do:      snapshots/raw.(jpg|png|bmp) — bez nowych pętli, w tym samym miejscu co last_frame
- Automatyczny wybór formatu wyjściowego (JPG→PNG→BMP) i zapamiętanie go (wspólny dla obu zapisów)
- Atomowy zapis przez .tmp + os.replace
- W heartbeat i logach podajemy faktyczną ścieżkę do last_frame z wybranym rozszerzeniem

ENV:
  DETECTOR=none|haar|tflite|ssd
  VISION_HUMAN=0|1
  VISION_FACE_EVERY=5
  VISION_MIN_SCORE=0.5
  VISION_EVERY=2
  TFLITE_MODEL=models/efficientdet_lite0.tflite
  SSD_CLASSES="*" lub lista (np. "person,chair")
  PREVIEW_ROT=0|90|180|270
  SAVE_LAST_EVERY=10
  DISABLE_LCD=0|1
  NO_DRAW=0|1
  BUS_PUB_PORT=5555
  LAST_FRAME_EXT=.jpg|.png|.bmp   # opcjonalnie wymuś rozszerzenie dla zapisów
  SNAP_DIR / SNAP_BASE             # katalog na snapshots (RAW/PROC); domyślnie ~/robot/snapshots
"""

from __future__ import annotations
import os, sys, time, json
from pathlib import Path
from typing import List, Optional, Set, Tuple

from apps.camera.utils import open_camera

# ── ENV / ustawienia
HUMAN_EN         = int(os.getenv("VISION_HUMAN", "0"))
FACE_EVERY       = max(1, int(os.getenv("VISION_FACE_EVERY", "5")))
ROT              = int(os.getenv("PREVIEW_ROT", "0") or 0)  # 0/90/180/270
SAVE_LAST_EVERY  = max(1, int(os.getenv("SAVE_LAST_EVERY", "10")))
ENV_DISABLE_LCD  = (os.getenv("DISABLE_LCD", "0").strip() == "1")
ENV_NO_DRAW      = (os.getenv("NO_DRAW", "0").strip() == "1")
BUS_PUB_PORT     = int(os.getenv("BUS_PUB_PORT", "5555"))
DETECTOR         = (os.getenv("DETECTOR", "none") or "none").strip().lower()
if HUMAN_EN and DETECTOR == "none":
    DETECTOR = "haar"  # kompatybilność z wcześniejszym VISION_HUMAN

VISION_MIN_SCORE = float(os.getenv("VISION_MIN_SCORE", "0.55"))
VISION_EVERY     = max(1, int(os.getenv("VISION_EVERY", "2")))
TFLITE_MODEL     = os.getenv("TFLITE_MODEL", "models/efficientdet_lite0.tflite").strip()
FORCED_EXT       = os.getenv("LAST_FRAME_EXT", "").strip().lower()  # np. ".png"

# ── Ścieżki
REPO_ROOT  = Path(__file__).resolve().parents[2]   # .../Rider-Pi
DATA_DIR   = REPO_ROOT / "data"
LAST_BASE  = DATA_DIR / "last_frame"               # bez rozszerzenia
DATA_DIR.mkdir(parents=True, exist_ok=True)

# katalog snapshotów do podglądu z dashboardu (RAW/PROC)
SNAP_DIR = os.getenv("SNAP_DIR") or os.getenv("SNAP_BASE") or str((REPO_ROOT / "snapshots"))
Path(SNAP_DIR).mkdir(parents=True, exist_ok=True)

# ── OpenCV
try:
    import cv2
    import numpy as np
except Exception as e:
    print("[preview] Brak OpenCV: sudo apt-get install -y python3-opencv", e, file=sys.stderr)
    sys.exit(1)

# ── BUS publisher (preferuj common.bus, w razie czego czysty ZMQ)
PUB_kind = "zmq"
PUB = None
try:
    from common.bus import BusPub
    PUB = BusPub()
    PUB_kind = "bus"
except Exception:
    try:
        import zmq
        _ctx = zmq.Context.instance()
        _pub = _ctx.socket(zmq.PUB)
        _pub.connect(f"tcp://127.0.0.1:{BUS_PUB_PORT}")
        PUB_kind = "zmq"
    except Exception as e:
        print("[preview] pyzmq niedostępny (publish off):", e, file=sys.stderr)
        _pub = None

def publish(topic: str, payload: dict, add_ts: bool=False):
    if add_ts:
        payload = dict(payload)
        payload["ts"] = time.time()
    try:
        if PUB_kind == "bus" and PUB is not None:
            PUB.publish(topic, payload)
        elif PUB_kind == "zmq" and _pub is not None:
            _pub.send_string(f"{topic} {json.dumps(payload, ensure_ascii=False)}")
    except Exception:
        pass

# ── Heartbeat helper (podamy realną ścieżkę last_frame)
_last_frame_used_path: Optional[str] = None
def hb_publish(fps: float, lcd_active: bool):
    payload = {
        "mode": "preview",
        "fps": round(float(fps), 1),
        "lcd": {"active": bool(lcd_active), "no_draw": ENV_NO_DRAW, "rot": ROT},
    }
    if _last_frame_used_path:
        payload["last_frame_path"] = _last_frame_used_path
    publish("camera.heartbeat", payload, add_ts=True)

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

from PIL import Image  # PIL używany do LCD

def rotate_bgr(img_bgr, rot_deg: int):
    if rot_deg == 90:
        return cv2.rotate(img_bgr, cv2.ROTATE_90_CLOCKWISE)
    if rot_deg == 180:
        return cv2.rotate(img_bgr, cv2.ROTATE_180)
    if rot_deg == 270:
        return cv2.rotate(img_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img_bgr

def bgr_to_pil(img_bgr):
    img_bgr = rotate_bgr(img_bgr, ROT)
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(img_rgb)

# ── zapis obrazów: wybór działającego rozszerzenia i atomowy zapis
_SELECTED_EXT: Optional[str] = None  # ".jpg" | ".png" | ".bmp"

def _try_encode(ext: str, img, params) -> Optional[bytes]:
    try:
        ok, buf = cv2.imencode(ext, img, params)
        if ok:
            return buf.tobytes()
    except Exception:
        pass
    return None

def _select_working_ext(img) -> str:
    # jeśli wymuszone przez ENV i działa – użyj
    if FORCED_EXT in (".jpg", ".jpeg", ".png", ".bmp"):
        test = {
            ".jpg": [int(cv2.IMWRITE_JPEG_QUALITY), 80],
            ".jpeg":[int(cv2.IMWRITE_JPEG_QUALITY), 80],
            ".png": [int(cv2.IMWRITE_PNG_COMPRESSION), 3],
            ".bmp": [],
        }
        if _try_encode(FORCED_EXT, img, test[FORCED_EXT]) is not None:
            return FORCED_EXT if FORCED_EXT != ".jpeg" else ".jpg"
    # kolejność preferencji
    for ext, params in [
        (".jpg", [int(cv2.IMWRITE_JPEG_QUALITY), 80]),
        (".png", [int(cv2.IMWRITE_PNG_COMPRESSION), 3]),
        (".bmp", []),
    ]:
        if _try_encode(ext, img, params) is not None:
            return ext
    # awaryjnie
    return ".bmp"

def _atomic_write_bytes(path: Path, data: bytes) -> bool:
    tmp = str(path) + ".tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, str(path))
        return True
    except Exception:
        try: os.remove(tmp)
        except Exception: pass
        return False

def save_last_frame(frame_bgr):
    """Zapisz klatkę: wybór działającego formatu (jednorazowo), potem atomowy zapis."""
    global _SELECTED_EXT, _last_frame_used_path
    try:
        img = rotate_bgr(frame_bgr, ROT)
        if _SELECTED_EXT is None:
            _SELECTED_EXT = _select_working_ext(img)
            print(f"[preview] last_frame: selected ext = {_SELECTED_EXT}", flush=True)
        # parametry enkodera dla wybranego rozszerzenia
        params = {
            ".jpg": [int(cv2.IMWRITE_JPEG_QUALITY), 80],
            ".png": [int(cv2.IMWRITE_PNG_COMPRESSION), 3],
            ".bmp": [],
        }[_SELECTED_EXT]
        data = _try_encode(_SELECTED_EXT, img, params)
        if data is None:
            # jeżeli nagle padło – dobierz ponownie
            _SELECTED_EXT = _select_working_ext(img)
            print(f"[preview] last_frame: reselected ext = {_SELECTED_EXT}", flush=True)
            params = {
                ".jpg": [int(cv2.IMWRITE_JPEG_QUALITY), 80],
                ".png": [int(cv2.IMWRITE_PNG_COMPRESSION), 3],
                ".bmp": [],
            }[_SELECTED_EXT]
            data = _try_encode(_SELECTED_EXT, img, params)
        out_path = LAST_BASE.with_suffix(_SELECTED_EXT)
        if data is not None and _atomic_write_bytes(out_path, data):
            _last_frame_used_path = str(out_path)
            # loguj rzadziej, by nie spamować
            print(f"[preview] last_frame updated: {out_path}", flush=True)
        else:
            print(f"[preview] save_last_frame FAILED for ext={_SELECTED_EXT}", flush=True)
    except Exception as e:
        print(f"[preview] save_last_frame ERROR: {e}", flush=True)

def save_raw_snapshot(frame_bgr):
    """Dodatkowy zapis RAW do snapshots/raw.(ext) — bez nowych pętli, używa tego samego rozszerzenia."""
    global _SELECTED_EXT
    try:
        img = rotate_bgr(frame_bgr, ROT)
        if _SELECTED_EXT is None:
            _SELECTED_EXT = _select_working_ext(img)
            print(f"[preview] raw snapshot: selected ext = {_SELECTED_EXT}", flush=True)
        params = {
            ".jpg": [int(cv2.IMWRITE_JPEG_QUALITY), 80],
            ".png": [int(cv2.IMWRITE_PNG_COMPRESSION), 3],
            ".bmp": [],
        }[_SELECTED_EXT]
        data = _try_encode(_SELECTED_EXT, img, params)
        if data is None:
            _SELECTED_EXT = _select_working_ext(img)
            print(f"[preview] raw snapshot: reselected ext = {_SELECTED_EXT}", flush=True)
            params = {
                ".jpg": [int(cv2.IMWRITE_JPEG_QUALITY), 80],
                ".png": [int(cv2.IMWRITE_PNG_COMPRESSION), 3],
                ".bmp": [],
            }[_SELECTED_EXT]
            data = _try_encode(_SELECTED_EXT, img, params)
        out_path = Path(SNAP_DIR) / f"raw{_SELECTED_EXT}"
        if data is not None and _atomic_write_bytes(out_path, data):
            # dla kompatybilności UI: jeśli nie .jpg, zrób symlink raw.jpg → raw.<ext>
            if _SELECTED_EXT != ".jpg":
                try: (Path(SNAP_DIR) / "raw.jpg").unlink(missing_ok=True)
                except Exception: pass
                try: (Path(SNAP_DIR) / "raw.jpg").symlink_to(out_path.name)
                except Exception: pass
        else:
            print(f"[preview] save_raw_snapshot FAILED ext={_SELECTED_EXT}", flush=True)
    except Exception as e:
        print(f"[preview] save_raw_snapshot ERROR: {e}", flush=True)

# ── Kamera (Picamera2 → V4L2 fallback)
# korzystamy z utils.open_camera

# ── Detektory
def parse_ssd_classes_env() -> Set[str]:
    raw = (os.getenv("SSD_CLASSES", "person") or "").strip().lower()
    if raw in ("*", "", "all"):
        return set()  # brak filtra
    return {x.strip() for x in raw.split(",") if x.strip()}

CLASSES_SSD = ["background","aeroplane","bicycle","bird","boat","bottle","bus","car","cat",
               "chair","cow","diningtable","dog","horse","motorbike","person","pottedplant",
               "sheep","sofa","train","tvmonitor"]

def ssd_load():
    proto = os.path.join("models","ssd","MobileNetSSD_deploy.prototxt")
    model = os.path.join("models","ssd","MobileNetSSD_deploy.caffemodel")
    if not os.path.isfile(proto): raise FileNotFoundError(f"Brak prototxt: {proto}")
    if not os.path.isfile(model): raise FileNotFoundError(f"Brak caffemodel: {model}")
    if os.path.getsize(model) < 5_000_000:
        raise IOError(f"Uszkodzony/niepełny model Caffe (size={os.path.getsize(model)} B) – potrzebny ~23MB.")
    net = cv2.dnn.readNetFromCaffe(proto, model)
    return net

class TFLiteEffDet:
    def __init__(self, path: str):
        try:
            from tflite_runtime.interpreter import Interpreter
        except Exception:
            from tensorflow.lite.python.interpreter import Interpreter  # type: ignore
        self.interp = Interpreter(model_path=path, num_threads=int(os.getenv("TFLITE_THREADS","2")))
        self.interp.allocate_tensors()
        self.input_details = self.interp.get_input_details()
        self.output_details = self.interp.get_output_details()
        ishape = self.input_details[0]["shape"]
        self.in_h, self.in_w = int(ishape[1]), int(ishape[2])

    def infer(self, frame_bgr, score_thr: float):
        # Uogólniony parser TF2 Detection API (boxes, classes, scores, count)
        img = cv2.resize(frame_bgr, (self.in_w, self.in_h))
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        inp = np.expand_dims(rgb, 0).astype(np.uint8)
        self.interp.set_tensor(self.input_details[0]["index"], inp)
        self.interp.invoke()

        def get(idx):
            return self.interp.get_tensor(self.output_details[idx]["index"])
        outs = [get(i) for i in range(len(self.output_details))]

        boxes = None; classes = None; scores = None; count = None
        for a in outs:
            shp = tuple(a.shape)
            if len(shp)==3 and shp[2]==4: boxes = a
            elif len(shp)==2 and shp[1] in (10,25,100):
                pass
            elif len(shp)==2 and shp[1]==1: count = a
        for a in outs:
            if a.dtype in (np.float32, np.float16) and len(a.shape)==2 and a.shape[1] in (10,25,100):
                if scores is None: scores = a
                else: scores = a if a.mean() > scores.mean() else scores
            if a.dtype in (np.float32, np.int32, np.int64) and len(a.shape)==2 and a.shape[1] in (10,25,100):
                if classes is None: classes = a

        if boxes is None or scores is None or classes is None:
            return []

        boxes = boxes[0]; scores = scores[0]; classes = classes[0]
        n = len(scores) if count is None else int(count.flatten()[0])

        H, W = frame_bgr.shape[:2]
        detections: List[Tuple[str,float,Tuple[int,int,int,int]]] = []
        COCO = {0:"person"}  # minimalny mapping; rozbudujesz wg potrzeb
        for i in range(min(n, len(scores))):
            sc = float(scores[i])
            if sc < score_thr: continue
            cls_idx = int(classes[i])
            name = COCO.get(cls_idx, "obj")
            y1, x1, y2, x2 = boxes[i]  # [0..1]
            x1 = int(max(0, min(1, x1)) * W); x2 = int(max(0, min(1, x2)) * W)
            y1 = int(max(0, min(1, y1)) * H); y2 = int(max(0, min(1, y2)) * H)
            if x2<=x1 or y2<=y1: continue
            detections.append((name, sc, (x1,y1,x2,y2)))
        return detections

def publish_detections(frame, detections: List[Tuple[str,float,Tuple[int,int,int,int]]]):
    if not detections:
        return
    h, w = frame.shape[:2]
    try:
        publish("vision.detections", {
            "size": [int(w), int(h)],
            "items": [
                {"name": name, "score": float(conf),
                 "bbox": [int(x1), int(y1), int(x2-x1), int(y2-y1)]}
                for (name, conf, (x1,y1,x2,y2)) in detections
            ]
        }, add_ts=True)
    except Exception:
        pass
    # kompatybilny topic dla 'person'
    for name, conf, (x1,y1,x2,y2) in detections:
        if name.lower() == "person":
            try:
                publish("vision.person", {
                    "present": True, "score": float(conf),
                    "bbox": [int(x1),int(y1),int(x2-x1),int(y2-y1)]
                }, add_ts=True)
            except Exception:
                pass

def draw_overlay(img, detections):
    for name, conf, (x1,y1,x2,y2) in detections:
        cv2.rectangle(img,(x1,y1),(x2,y2),(0,255,255),2)
        cv2.putText(img, f"{name}:{conf:.2f}", (x1, max(0,y1-5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,255), 1)

def main():
    # Kamera
    read, _ = open_camera((320,240))

    # Detektor init
    det_kind = DETECTOR
    det = None
    ssd_filter = parse_ssd_classes_env()

    if det_kind == "ssd":
        try:
            det = ssd_load()
            print(f"[det] SSD READY | classes={'ALL' if not ssd_filter else ','.join(sorted(ssd_filter))}")
        except Exception as e:
            print(f"[det] SSD init FAILED: {e} → DETECTOR=none", flush=True)
            det_kind = "none"
    elif det_kind == "tflite":
        if not os.path.isfile(TFLITE_MODEL):
            print(f"[det] TFLite model not found: {TFLITE_MODEL} → DETECTOR=none", flush=True)
            det_kind = "none"
        else:
            try:
                det = TFLiteEffDet(TFLITE_MODEL)
                print(f"[det] TFLite READY | model={TFLITE_MODEL}", flush=True)
            except Exception as e:
                print(f"[det] TFLite init FAILED: {e} → DETECTOR=none", flush=True)
                det_kind = "none"
    elif det_kind == "haar":
        pass  # zainicjalizujemy niżej w pętli (lekki)

    print(f"[preview] Start. LCD={'ON' if (LCD_ok and not ENV_NO_DRAW) else 'OFF (headless)'}; "
          f"ROT={ROT}°; SAVE_LAST_EVERY={SAVE_LAST_EVERY}; DETECTOR={det_kind}; PUB={PUB_kind}; "
          f"LAST_BASE={LAST_BASE} (auto ext); SNAP_DIR={SNAP_DIR}", flush=True)

    frames = 0
    t0 = time.time()
    t_hb_last = 0.0
    face_cascade = None

    try:
        while True:
            ok, frame = read()
            if not ok:
                time.sleep(0.02)
                continue

            # Detekcja (opcjonalnie)
            detections: List[Tuple[str,float,Tuple[int,int,int,int]]] = []

            if det_kind == "haar":
                if face_cascade is None:
                    try:
                        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
                    except Exception:
                        face_cascade = None
                if face_cascade is not None and (frames % FACE_EVERY == 0):
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=3, minSize=(40,40))
                    for (x, y, w, h) in faces:
                        detections.append(("person", 0.90, (x, y, x+w, y+h)))

            elif det_kind == "ssd":
                if frames % VISION_EVERY == 0:
                    blob = cv2.dnn.blobFromImage(cv2.resize(frame,(300,300)),
                                                 0.007843,(300,300),127.5,swapRB=True,crop=False)
                    det.setInput(blob)
                    raw = det.forward()
                    h, w = frame.shape[:2]
                    for i in range(raw.shape[2]):
                        conf = float(raw[0,0,i,2])
                        if conf < VISION_MIN_SCORE: continue
                        cls_id = int(raw[0,0,i,1])
                        x1 = int(raw[0,0,i,3]*w); y1 = int(raw[0,0,i,4]*h)
                        x2 = int(raw[0,0,i,5]*w); y2 = int(raw[0,0,i,6]*h)
                        x1 = max(0,min(x1,w-1)); y1 = max(0,min(y1,h-1))
                        x2 = max(0,min(x2,w-1)); y2 = max(0,min(y2,h-1))
                        if x2<=x1 or y2<=y1: continue
                        name = CLASSES_SSD[cls_id] if 0<=cls_id<len(CLASSES_SSD) else str(cls_id)
                        lname = name.lower()
                        if ssd_filter and (lname not in ssd_filter):
                            continue
                        detections.append((name, conf, (x1,y1,x2,y2)))

            elif det_kind == "tflite":
                if frames % VISION_EVERY == 0:
                    try:
                        detections = det.infer(frame, VISION_MIN_SCORE)  # type: ignore
                    except Exception:
                        detections = []

            # Overlay i publikacja
            if detections:
                publish_detections(frame, detections)

            # FPS + overlay co 10 klatek (overlay tylko jeśli rysujemy)
            elapsed = max(1e-6, (time.time() - t0))
            fps = (frames+1) / elapsed
            out = frame.copy()
            if detections and (LCD_ok and not ENV_NO_DRAW):
                draw_overlay(out, detections)
            if LCD_ok and not ENV_NO_DRAW and (frames % 10 == 0):
                cv2.putText(out, f"{fps:.1f} fps", (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,0,0), 1)

            # Zapis last_frame + RAW snapshot — pierwsza klatka od razu, potem co SAVE_LAST_EVERY
            if frames == 0 or (frames % SAVE_LAST_EVERY == 0):
                save_last_frame(frame)
                save_raw_snapshot(frame)

            # Wyświetlenie na LCD
            if LCD_ok and not ENV_NO_DRAW:
                try:
                    disp.ShowImage(bgr_to_pil(out))
                except Exception:
                    pass

            # Heartbeat co ~1s
            if (time.time() - t_hb_last) >= 1.0:
                hb_publish(fps=fps, lcd_active=(LCD_ok and not ENV_NO_DRAW))
                t_hb_last = time.time()

            frames += 1

    except KeyboardInterrupt:
        pass
    finally:
        # zgaś LCD po wyjściu (best-effort)
        if LCD_ok:
            try:
                os.system("sudo -n python3 ops/lcdctl.py off >/dev/null 2>&1 || sudo python3 ops/lcdctl.py off")
            except Exception:
                pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
