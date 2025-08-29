# apps/vision/dispatcher.py
"""
Zbiera zdarzenia z detektorów (HAAR/SSD/itd.), normalizuje je,
robi debouncing/histerezę i publikuje prosty stan obecności.
Topics IN:  vision.face, vision.person, vision.detections
Topics OUT: vision.state, autonomy.perception (opcjonalnie), ui.face (opcjonalnie)
"""

import os
import time
import json
import threading
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

# --- ZMQ minimal wrapper (podmień na common.bus, jeśli kiedyś wydzielimy) ---
import zmq

BUS_PUB_PORT = int(os.getenv("BUS_PUB_PORT", "5555"))   # my -> world (PUB łączy się do XSUB)
BUS_SUB_PORT = int(os.getenv("BUS_SUB_PORT", "5556"))   # world -> me (SUB łączy się do XPUB)
ZMQ_ADDR_PUB = f"tcp://127.0.0.1:{BUS_PUB_PORT}"
ZMQ_ADDR_SUB = f"tcp://127.0.0.1:{BUS_SUB_PORT}"

PUB = None  # type: ignore
SUB = None  # type: ignore

def zmq_pub():
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.PUB)
    s.connect(ZMQ_ADDR_PUB)
    return s

def zmq_sub(topics: List[str]):
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.SUB)
    s.connect(ZMQ_ADDR_SUB)
    for t in topics:
        s.setsockopt_string(zmq.SUBSCRIBE, t)
    return s

def pub(topic: str, payload: Dict[str, Any]):
    try:
        msg = f"{topic} {json.dumps(payload, ensure_ascii=False)}"
        PUB.send_string(msg)  # type: ignore
    except Exception as e:
        print(f"[dispatcher] pub err: {e}", flush=True)

def sub_recv():
    """
    Odbiór prostego formatu 'topic<spacja>{json}'.
    Jeśli payload nie jest JSON-em — zwraca {'raw': '...'}.
    """
    raw = SUB.recv_string()  # type: ignore
    if " " in raw:
        topic, payload = raw.split(" ", 1)
    else:
        topic, payload = raw, "{}"
    try:
        data = json.loads(payload)
    except Exception:
        data = {"raw": payload}
    return topic, data

# --- Parametry histerezy/debouncera (ENV) ---
P_ON_N    = int(os.getenv("VISION_ON_CONSECUTIVE", "3"))   # ile kolejnych pozytywów, by uznać „present=true”
P_OFF_TT  = float(os.getenv("VISION_OFF_TTL_SEC", "2.0"))  # po ilu sekundach bez pozytywów uznać „present=false”
MIN_SCORE = float(os.getenv("VISION_MIN_SCORE", "0.50"))   # minimalny próg score

LOG_EVERY = int(os.getenv("LOG_EVERY", "10"))

# --- Stan wewnętrzny ---
@dataclass
class PresenceState:
    present: bool = False
    last_pos_ts: float = 0.0
    consecutive_pos: int = 0
    confidence: float = 0.0

STATE = PresenceState()
_frame = 0  # licznik dla rzadkich logów

# --- Normalizacja wejścia ---
def normalize_event(topic: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Sprowadzamy HAAR/SSD/hybrid do: {"kind": "face"/"person", "present": bool, "score": float, "bbox": [x,y,w,h] or None}
    Zakładamy, że detektory wysyłają przynajmniej score; gdy brak, używamy domyślnych.
    """
    kind = "face" if "face" in topic else ("person" if "person" in topic else "det")
    def _as_float(v, default=0.0):
        try:
            return float(v)
        except Exception:
            return float(default)
    score = _as_float(data.get("score", data.get("confidence", 1.0)), 1.0)
    present = bool(data.get("present", True))  # brak = pozytyw
    bbox = data.get("bbox")
    return {"kind": kind, "present": present, "score": score, "bbox": bbox}

def update_presence(evt: Dict[str, Any]):
    now = time.time()
    global STATE, _frame
    _frame += 1

    if evt["present"] and evt["score"] >= MIN_SCORE:
        STATE.consecutive_pos += 1
        STATE.last_pos_ts = now
        # confidence: prosty running max z lekkim opadaniem
        STATE.confidence = max(STATE.confidence * 0.9, float(evt["score"]))
        if not STATE.present and STATE.consecutive_pos >= P_ON_N:
            STATE.present = True
            announce_state()
    else:
        # brak pozytywów — sprawdzamy TTL
        if STATE.present and (now - STATE.last_pos_ts) >= P_OFF_TT:
            STATE.present = False
            STATE.consecutive_pos = 0
            STATE.confidence = 0.0
            announce_state()

    # okazjonalny log
    if LOG_EVERY > 0 and (_frame % LOG_EVERY == 0):
        print(f"[dispatcher] pres={STATE.present} conf={STATE.confidence:.2f} consec={STATE.consecutive_pos}", flush=True)

def announce_state():
    payload = {"present": STATE.present, "confidence": round(STATE.confidence, 3), "ts": time.time()}
    pub("vision.state", payload)
    # (opcjonalnie) sygnały do innych modułów:
    # pub("autonomy.perception", {"type":"presence", **payload})
    # pub("ui.face", {"mood": "awake" if STATE.present else "idle"})
    print(f"[dispatcher] announce vision.state -> {payload}", flush=True)

def rx_loop():
    print("[dispatcher] rx_loop started", flush=True)
    while True:
        try:
            topic, data = sub_recv()
            if not topic.startswith("vision."):
                continue
            evt = normalize_event(topic, data)
            if evt is None:
                continue
            update_presence(evt)
        except KeyboardInterrupt:
            break
        except Exception as e:
            # Nie zacinamy pętli na pojedynczym błędzie
            print(f"[dispatcher] err: {e}", flush=True)
            time.sleep(0.02)

def heartbeat_loop():
    # Co jakiś czas emituj heartbeat (do debug/logów)
    while True:
        try:
            pub("vision.dispatcher.heartbeat", {"ts": time.time(), "present": STATE.present})
            time.sleep(5)
        except KeyboardInterrupt:
            break
        except Exception:
            time.sleep(5)

if __name__ == "__main__":
    print("[dispatcher] starting (topics: vision.face/person/detections)", flush=True)
    PUB = zmq_pub()
    SUB = zmq_sub(["vision.face", "vision.person", "vision.detections"])
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    # Wyślij stan początkowy (present=False), żeby API od razu miało /state:
    announce_state()
    rx_loop()
