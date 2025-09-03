#!/usr/bin/env python3
# apps/vision/dispatcher.py
"""
Zbiera zdarzenia z detektorów (HAAR/SSD/itd.), normalizuje je,
robi debouncing/histerezę i publikuje prosty stan obecności.
IN : vision.face, vision.person, vision.detections
OUT: vision.state, vision.dispatcher.heartbeat
"""

import os, time, json, threading
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple

import zmq

BUS_PUB_PORT = int(os.getenv("BUS_PUB_PORT", "5555"))
BUS_SUB_PORT = int(os.getenv("BUS_SUB_PORT", "5556"))
ZMQ_ADDR_PUB = f"tcp://127.0.0.1:{BUS_PUB_PORT}"
ZMQ_ADDR_SUB = f"tcp://127.0.0.1:{BUS_SUB_PORT}"

# Histereza / debouncing (ENV)
P_ON_N    = int(os.getenv("VISION_ON_CONSECUTIVE", "3"))     # ile kolejnych pozytywów, by włączyć present=True
P_OFF_TT  = float(os.getenv("VISION_OFF_TTL_SEC", "2.0"))    # po ilu sekundach ciszy zgasić present
MIN_SCORE = float(os.getenv("VISION_MIN_SCORE", "0.50"))     # minimalny próg score
LOG_EVERY = int(os.getenv("LOG_EVERY", "10"))

PUB: Optional[zmq.Socket] = None
SUB: Optional[zmq.Socket] = None
STATE_LOCK = threading.Lock()

def zmq_pub() -> zmq.Socket:
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.PUB)
    s.connect(ZMQ_ADDR_PUB)
    return s

def zmq_sub(topics: List[str]) -> zmq.Socket:
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.SUB)
    s.connect(ZMQ_ADDR_SUB)
    # krótki timeout dla responsywności
    try:
        s.setsockopt(zmq.RCVTIMEO, 1000)
    except Exception:
        pass
    for t in topics:
        s.setsockopt_string(zmq.SUBSCRIBE, t)
    return s

def _json_loads(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}

def sub_recv() -> Tuple[str, Dict[str, Any]]:
    """
    Odbiór z SUB — wspiera single-frame ("topic payload") i multipart.
    Zwraca: (topic, data:dict)
    """
    assert SUB is not None
    parts = SUB.recv_multipart()  # list[bytes]
    if not parts:
        return "", {}
    if len(parts) == 1:
        s = parts[0].decode("utf-8", "replace")
        if " " in s:
            topic, payload = s.split(" ", 1)
            return topic, _json_loads(payload)
        return s, {}
    topic = parts[0].decode("utf-8", "replace")
    try:
        payload = "".join(p.decode("utf-8", "replace") for p in parts[1:])
        return topic, _json_loads(payload)
    except Exception:
        return topic, {"raw": "<binary>"}

def pub(topic: str, payload: Dict[str, Any]) -> None:
    try:
        assert PUB is not None
        PUB.send_string(f"{topic} {json.dumps(payload, ensure_ascii=False)}")
    except Exception as e:
        print(f"[dispatcher] pub err: {e}", flush=True)

# --- Stan wewnętrzny ---
@dataclass
class PresenceState:
    present: bool = False
    last_pos_ts: float = 0.0
    consecutive_pos: int = 0
    confidence: float = 0.0

STATE = PresenceState()
_FRAME = 0
_LAST_MODE: str = "idle"

def _as_float(v, default=0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)

def _best_detection(items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Wybierz najlepszą detekcję z listy (preferuj person/face, najwyższy score)."""
    if not items:
        return None
    # normalizuj klucz score
    scored = []
    for d in items:
        sc = _as_float(d.get("score", d.get("confidence", 0.0)), 0.0)
        lbl = (d.get("label") or d.get("class") or "").lower()
        scored.append((sc, lbl, d))
    # preferencja: person/face
    scored.sort(key=lambda t: (("person" in t[1]) or ("face" in t[1]), t[0]), reverse=True)
    return scored[0][2]

def normalize_event(topic: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Sprowadzamy HAAR/SSD/hybrid do:
      {"kind": "face"/"person"/"det", "present": bool, "score": float, "bbox": [...], "mode": str}
    Obsługuje też vision.detections z listą obiektów.
    """
    if topic == "vision.detections":
        items = data.get("items") or data.get("detections") or data.get("objects") or []
        best = _best_detection(items)
        if not best:
            return {"kind": "det", "present": False, "score": 0.0, "bbox": None, "mode": data.get("mode") or "det"}
        lbl = (str(best.get("label") or best.get("class") or "")).lower()
        kind = "person" if "person" in lbl else ("face" if "face" in lbl else "det")
        score = _as_float(best.get("score", best.get("confidence", 0.0)), 0.0)
        return {"kind": kind, "present": score >= MIN_SCORE, "score": score,
                "bbox": best.get("bbox"), "mode": data.get("mode") or "ssd"}

    kind = "face" if "face" in topic else ("person" if "person" in topic else "det")
    score = _as_float(data.get("score", data.get("confidence", 1.0)), 1.0)
    present = bool(data.get("present", True))
    bbox = data.get("bbox")
    mode = data.get("mode") or ( "haar" if kind=="face" else ("ssd" if kind=="person" else "det") )
    return {"kind": kind, "present": present, "score": score, "bbox": bbox, "mode": mode}

def announce_state() -> None:
    with STATE_LOCK:
        payload = {
            "present": STATE.present,
            "confidence": round(STATE.confidence, 3),
            "mode": _LAST_MODE,
            "ts": time.time(),
        }
    pub("vision.state", payload)
    print(f"[dispatcher] announce vision.state -> {payload}", flush=True)

def update_presence(evt: Dict[str, Any]) -> None:
    now = time.time()
    global _FRAME, _LAST_MODE
    _FRAME += 1

    should_announce_on = False
    should_announce_off = False

    with STATE_LOCK:
        if isinstance(evt.get("mode"), str) and evt["mode"]:
            _LAST_MODE = evt["mode"]

        if evt["present"] and evt["score"] >= MIN_SCORE:
            STATE.consecutive_pos += 1
            STATE.last_pos_ts = now
            STATE.confidence = max(STATE.confidence * 0.9, float(evt["score"]))
            if not STATE.present and STATE.consecutive_pos >= P_ON_N:
                STATE.present = True
                should_announce_on = True
        else:
            # Negatywy/zanik — OFF po TTL
            if STATE.present and (now - STATE.last_pos_ts) >= P_OFF_TT:
                STATE.present = False
                STATE.consecutive_pos = 0
                STATE.confidence = 0.0
                should_announce_off = True

        if LOG_EVERY > 0 and (_FRAME % LOG_EVERY == 0):
            print(
                f"[dispatcher] pres={STATE.present} conf={STATE.confidence:.2f} "
                f"consec={STATE.consecutive_pos} mode={_LAST_MODE}",
                flush=True,
            )

    if should_announce_on or should_announce_off:
        announce_state()

def rx_loop() -> None:
    print("[dispatcher] rx_loop started", flush=True)
    while True:
        try:
            topic, data = sub_recv()
            if not topic.startswith("vision."):
                continue
            evt = normalize_event(topic, data)
            if evt:
                update_presence(evt)
        except KeyboardInterrupt:
            break
        except zmq.Again:
            # timeout — pozwala na responsywne zamknięcie
            pass
        except Exception as e:
            print(f"[dispatcher] err: {e}", flush=True)
            time.sleep(0.02)

def heartbeat_loop() -> None:
    while True:
        try:
            with STATE_LOCK:
                present = STATE.present
            pub("vision.dispatcher.heartbeat", {"ts": time.time(), "present": present})
            time.sleep(5)
        except KeyboardInterrupt:
            break
        except Exception:
            time.sleep(5)

def ttl_loop() -> None:
    """Watchdog ciszy: gasi present po P_OFF_TT sekundach bez pozytywów."""
    while True:
        try:
            now = time.time()
            announce = False
            with STATE_LOCK:
                if STATE.present and (now - STATE.last_pos_ts) >= P_OFF_TT:
                    STATE.present = False
                    STATE.consecutive_pos = 0
                    STATE.confidence = 0.0
                    announce = True
            if announce:
                announce_state()
            time.sleep(0.2)
        except KeyboardInterrupt:
            break
        except Exception:
            time.sleep(0.2)

if __name__ == "__main__":
    print("[dispatcher] starting (topics: vision.face/person/detections)", flush=True)
    PUB = zmq_pub()
    SUB = zmq_sub(["vision.face", "vision.person", "vision.detections"])
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    threading.Thread(target=ttl_loop, daemon=True).start()
    announce_state()  # początkowy stan
    rx_loop()
