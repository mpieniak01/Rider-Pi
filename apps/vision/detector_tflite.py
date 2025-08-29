#!/usr/bin/env python3
# apps/vision/dispatcher.py
"""
Zbiera zdarzenia z detektorów (HAAR/SSD/itd.), normalizuje je,
robi debouncing/histerezę i publikuje prosty stan obecności.
Topics IN:  vision.face, vision.person, vision.detections
Topics OUT: vision.state, autonomy.perception (opcjonalnie), ui.face (opcjonalnie)
"""

import os, time, json, threading, queue
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

# --- ZMQ minimal wrapper (podmień na common.bus, jeśli chcesz) ---
import zmq

BUS_PUB_PORT = int(os.getenv("BUS_PUB_PORT", "5555"))   # my -> world
BUS_SUB_PORT = int(os.getenv("BUS_SUB_PORT", "5556"))   # world -> me
ZMQ_ADDR_PUB = f"tcp://127.0.0.1:{BUS_PUB_PORT}"
ZMQ_ADDR_SUB = f"tcp://127.0.0.1:{BUS_SUB_PORT}"

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
    msg = f"{topic} {json.dumps(payload, ensure_ascii=False)}"
    PUB.send_string(msg)

def sub_recv():
    topic, payload = SUB.recv_multipart() if False else SUB.recv_string().split(" ", 1)
    try:
        data = json.loads(payload)
    except Exception:
        data = {"raw": payload}
    return topic, data

# --- Parametry histerezy/debouncera ---
P_ON_N   = int(os.getenv("VISION_ON_CONSECUTIVE", "3"))     # ile kolejnych pozytywów, by uznać „present=true”
P_OFF_TT = float(os.getenv("VISION_OFF_TTL_SEC", "2.0"))    # po ilu sekundach bez pozytywów uznać „present=false”
MIN_SCORE= float(os.getenv("VISION_MIN_SCORE", "0.50"))     # minimalny próg score

# --- Stan wewnętrzny ---
@dataclass
class PresenceState:
    present: bool = False
    last_pos_ts: float = 0.0
    consecutive_pos: int = 0
    confidence: float = 0.0

STATE = PresenceState()

# --- Normalizacja wejścia ---
def normalize_event(topic: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Sprowadzamy HAAR/SSD/hybrid do: {"kind": "face"/"person", "present": bool, "score": float, "bbox": [x,y,w,h] or None}
    Zakładamy, że detektory wysyłają przynajmniej score; gdy brak, używamy domyślnych.
    """
    kind = "face" if "face" in topic else ("person" if "person" in topic else "det")
    score = float(data.get("score", data.get("confidence", 1.0)))
    present = bool(data.get("present", True))  # brak = pozytyw
    bbox = data.get("bbox")
    return {"kind": kind, "present": present, "score": score, "bbox": bbox}

def update_presence(evt: Dict[str, Any]):
    now = time.time()
    global STATE

    if evt["present"] and evt["score"] >= MIN_SCORE:
        STATE.consecutive_pos += 1
        STATE.last_pos_ts = now
        # confidence: prosty running max z lekkim opadaniem
        STATE.confidence = max(STATE.confidence * 0.9, evt["score"])
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

def announce_state():
    payload = {"present": STATE.present, "confidence": round(STATE.confidence, 3), "ts": time.time()}
    pub("vision.state", payload)
    # (opcjonalnie) sygnały do innych modułów:
    # pub("autonomy.perception", {"type":"presence", **payload})
    # pub("ui.face", {"mood": "awake" if STATE.present else "idle"})

def rx_loop():
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
    rx_loop()
