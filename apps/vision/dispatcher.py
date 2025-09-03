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
from typing import Optional, Dict, Any, List

import zmq

BUS_PUB_PORT = int(os.getenv("BUS_PUB_PORT", "5555"))
BUS_SUB_PORT = int(os.getenv("BUS_SUB_PORT", "5556"))
ZMQ_ADDR_PUB = f"tcp://127.0.0.1:{BUS_PUB_PORT}"
ZMQ_ADDR_SUB = f"tcp://127.0.0.1:{BUS_SUB_PORT}"

# Histereza / debouncing (ENV)
P_ON_N    = int(os.getenv("VISION_ON_CONSECUTIVE", "3"))   # ile kolejnych pozytywów, by włączyć present=True
P_OFF_TT  = float(os.getenv("VISION_OFF_TTL_SEC", "2.0"))  # po ilu sekundach ciszy zgasić present
MIN_SCORE = float(os.getenv("VISION_MIN_SCORE", "0.50"))   # minimalny próg score
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
    # krótki timeout, żeby nie klinować zamknięcia i mieć responsywne przerwania
    s.setsockopt(zmq.RCVTIMEO, 1000)
    for t in topics:
        s.setsockopt_string(zmq.SUBSCRIBE, t)
    return s

def _json_loads(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}

def sub_recv() -> (str, Dict[str, Any]):
    """
    Odbiór z SUB — działa dla single-frame (send_string) i multipart (send_multipart).
    Zwraca: (topic:str, data:dict)
    """
    assert SUB is not None
    parts = SUB.recv_multipart()  # list[bytes]; single-frame -> len==1
    if not parts:
        return "", {}
    if len(parts) == 1:
        # single frame: "topic {json}" LUB samo "topic"
        txt = parts[0].decode("utf-8", errors="replace")
        if " " in txt:
            topic, payload = txt.split(" ", 1)
            return topic, _json_loads(payload)
        return txt, {}
    # multipart: [topic, payload, (opcjonalnie kolejne fragmenty payloadu)]
    topic = parts[0].decode("utf-8", errors="replace")
    try:
        payload = "".join(p.decode("utf-8", errors="replace") for p in parts[1:])
        return topic, _json_loads(payload)
    except Exception:
        # binarny payload (np. JPEG) — nie przetwarzamy go tutaj
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

def normalize_event(topic: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Sprowadzamy HAAR/SSD/hybrid do:
      {"kind": "face"/"person"/"det", "present": bool, "score": float, "bbox": [...], "mode": str}
    """
    kind = "face" if "face" in topic else ("person" if "person" in topic else "det")
    score = _as_float(data.get("score", data.get("confidence", 1.0)), 1.0)
    present = bool(data.get("present", True))
    bbox = data.get("bbox")
    mode = data.get("mode")
    if not isinstance(mode, str) or not mode:
        if kind == "face":
            mode = "haar"
        elif kind == "person":
            mode = data.get("source", "ssd")
        else:
            mode = "det"
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

    with STATE_LOCK:
        if isinstance(evt.get("mode"), str) and evt["mode"]:
            _LAST_MODE = evt["mode"]

        if evt["present"] and evt["score"] >= MIN_SCORE:
            STATE.consecutive_pos += 1
            STATE.last_pos_ts = now
            STATE.confidence = max(STATE.confidence * 0.9, float(evt["score"]))
            should_announce_on = (not STATE.present) and (STATE.consecutive_pos >= P_ON_N)
            if should_announce_on:
                STATE.present = True
        else:
            # Tryb „negatywny event” — OFF jeśli TTL upłynął
            if STATE.present and (now - STATE.last_pos_ts) >= P_OFF_TT:
                STATE.present = False
                STATE.consecutive_pos = 0
                STATE.confidence = 0.0
                should_announce_off = True
            else:
                should_announce_off = False

        # Log co N ramek
        if LOG_EVERY > 0 and (_FRAME % LOG_EVERY == 0):
            print(
                f"[dispatcher] pres={STATE.present} conf={STATE.confidence:.2f} "
                f"consec={STATE.consecutive_pos} mode={_LAST_MODE}",
                flush=True,
            )

        # Po wyjściu z sekcji krytycznej decydujemy, co wysłać
        announce_on = ('should_announce_on' in locals() and should_announce_on)
        announce_off = should_announce_off

    if announce_on or announce_off:
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
            # timeout — pozwala na responsywne zamknięcie, brak logu
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
    # wątki pomocnicze
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    threading.Thread(target=ttl_loop, daemon=True).start()
    # początkowy stan, żeby /state było od razu wypełnione
    announce_state()
    rx_loop()
