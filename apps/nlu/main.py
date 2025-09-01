#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apps/nlu/main.py — NLU v0.1 (PL → motion.cmd)

Sub:
  audio.transcript {"text":"...", "lang":"pl", "source":"voice", "is_final":true?}

Pub:
  motion.cmd  {"type":"drive|spin|stop", "dir":"forward|backward|left|right", "speed":0.4, "dur":1.0}

Założenia:
- Reagujemy tylko na lang=="pl" i source=="voice".
- Jeśli jest pole is_final, to działamy tylko gdy True (brak pola = działamy).
- Domyślne: prędkość i czas z ENV: NLU_DEFAULT_SPEED, NLU_DEFAULT_DUR.
- Rozpoznajemy: jedź/naprzód, cofnij, w lewo/prawo (spin), stop/stój/zatrzymaj,
  "szybciej"/"wolniej" (+/- 0.1 z clamp [0.1..1.0]).
- Liczby: "na 2 sekundy", "przez 1.5 s", "60%" oraz "na 0.6" → nadpisują speed/dur.
"""

import os, sys, time, json, re, unicodedata

PROJ_ROOT = "/home/pi/robot"
if PROJ_ROOT not in sys.path:
    sys.path.insert(0, PROJ_ROOT)

# bezpieczne printy
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

from common.bus import BusPub, BusSub

SUB = BusSub("audio.transcript")
PUB = BusPub()

# --- ENV / stan ---
DEFAULT_SPEED = float(os.getenv("NLU_DEFAULT_SPEED", "0.5"))
DEFAULT_DUR   = float(os.getenv("NLU_DEFAULT_DUR", "1.0"))
SPEED_STEP    = float(os.getenv("NLU_SPEED_STEP",  "0.1"))

cur_speed = DEFAULT_SPEED   # pamiętamy „bieg domyślny” pomiędzy komendami

# --- utils ---

def log(msg):
    print(time.strftime("[%H:%M:%S]"), msg, flush=True)

def _bus_publish(topic: str, payload: dict):
    """Kompatybilnie z Twoim BusPub (tools/pub.py używa .send)."""
    for m in ("send", "publish", "pub"):
        if hasattr(PUB, m):
            return getattr(PUB, m)(topic, payload)
    raise AttributeError("BusPub bez send/publish/pub")

def strip_diacritics(s: str) -> str:
    # zamiana PL znaków na ASCII (prosty normalize)
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

def norm(txt: str) -> str:
    t = txt.lower().strip()
    t = strip_diacritics(t)
    # ujednolicenia
    t = re.sub(r"[^\w\s%.,]", " ", t)      # wytnij znaki innych klas (zostaw % i . , )
    t = re.sub(r"\s+", " ", t).strip()
    return t

# --- ekstrakcja liczb ---

_re_sec = re.compile(r"(?:na|przez)\s*(\d+(?:[.,]\d+)?)\s*(?:s|sek|sekundy|sekund|sek\.)\b")
_re_pct = re.compile(r"(\d{1,3})\s*%")
_re_spd = re.compile(r"(?:na|do)?\s*(0(?:[.,]\d+)?|1(?:[.,]0+)?)\b")  # 0..1

def extract_duration_s(txt_norm: str):
    m = _re_sec.search(txt_norm)
    if not m:
        return None
    val = m.group(1).replace(",", ".")
    try:
        return max(0.0, float(val))
    except Exception:
        return None

def extract_speed(txt_norm: str):
    # priorytet: procenty -> ułamki
    m = _re_pct.search(txt_norm)
    if m:
        try:
            pct = int(m.group(1))
            pct = max(0, min(100, pct))
            return max(0.0, min(1.0, pct/100.0))
        except Exception:
            pass
    m = _re_spd.search(txt_norm)
    if m:
        try:
            val = float(m.group(1).replace(",", "."))
            return max(0.0, min(1.0, val))
        except Exception:
            pass
    return None

# --- reguły intencji ---

FWD_PATTERNS = [
    r"\b(jedz|jedziesz|rusz|start)\b",          # "jedź", "rusz"
    r"\bdo przodu\b",
    r"\bnaprzod\b",
]
BACK_PATTERNS = [
    r"\b(cofnij|cofaj|wycofaj)\b",
    r"\b(do tylu|w tyl)\b",
]
LEFT_PATTERNS = [
    r"\b(w lewo)\b",
    r"\b(skrec|skrec)\s*w\s*lewo\b",
    r"\blewo\b",
]
RIGHT_PATTERNS = [
    r"\b(w prawo)\b",
    r"\b(skrec|skrec)\s*w\s*prawo\b",
    r"\bprawo\b",
]
STOP_PATTERNS = [
    r"\bstop\b",
    r"\bstoj\b",
    r"\bzatrzymaj\b",
    r"\bhalt\b",
]

FASTER_PATTERNS = [r"\bszybciej\b", r"\bprzyspiesz\b", r"\bzwieksz predkosc\b"]
SLOWER_PATTERNS = [r"\bwolniej\b", r"\bzwolnij\b", r"\bzmniejsz predkosc\b"]

def any_match(txt_norm: str, patterns) -> bool:
    return any(re.search(p, txt_norm) for p in patterns)

# --- decyzja → motion.cmd ---

def clamp_speed(s: float) -> float:
    return max(0.1, min(1.0, s))

def make_cmd_drive(direction: str, speed: float, dur: float):
    return {"type": "drive", "dir": direction, "speed": round(speed, 3), "dur": float(dur)}

def make_cmd_spin(direction: str, speed: float, dur: float):
    return {"type": "spin", "dir": direction, "speed": round(speed, 3), "dur": float(dur)}

def decide(txt_raw: str):
    """
    Zwraca dict motion.cmd lub None oraz ewentualnie nowy cur_speed (dla 'szybciej/wolniej').
    """
    global cur_speed
    t = norm(txt_raw)

    # modyfikatory
    dur = extract_duration_s(t)
    spd = extract_speed(t)

    # zmiany biegu domyślnego (szybciej/wolniej)
    if any_match(t, FASTER_PATTERNS):
        cur_speed = clamp_speed(cur_speed + SPEED_STEP)
        log(f"NLU: speed up → {cur_speed:.2f}")
        # jeśli nie ma jawnej akcji, kończymy (tylko zmiana biegu)
        # ale jeśli jest też kierunek, spd/dur zadziałają poniżej
    if any_match(t, SLOWER_PATTERNS):
        cur_speed = clamp_speed(cur_speed - SPEED_STEP)
        log(f"NLU: speed down → {cur_speed:.2f}")

    # STOP ma najwyższy priorytet
    if any_match(t, STOP_PATTERNS):
        return {"type": "stop"}, cur_speed

    # kierunki
    speed = spd if spd is not None else cur_speed
    dur_s = dur if dur is not None else DEFAULT_DUR

    if any_match(t, LEFT_PATTERNS):
        return make_cmd_spin("left", speed, dur_s), cur_speed
    if any_match(t, RIGHT_PATTERNS):
        return make_cmd_spin("right", speed, dur_s), cur_speed
    if any_match(t, BACK_PATTERNS):
        return make_cmd_drive("backward", speed, dur_s), cur_speed
    if any_match(t, FWD_PATTERNS) or re.search(r"\bdo przodu\b", t):
        return make_cmd_drive("forward", speed, dur_s), cur_speed

    # brak dopasowania → None
    return None, cur_speed

# --- pętla ---

def should_process(msg: dict) -> bool:
    # tylko pl i tylko voice
    if (msg.get("lang") or "").lower() != "pl":
        return False
    if (msg.get("source") or "").lower() != "voice":
        return False
    # jeśli is_final istnieje, wymagaj True
    if "is_final" in msg and not bool(msg.get("is_final")):
        return False
    return True

def main():
    log("NLU v0.1: start (sub audio.transcript → pub motion.cmd)")
    while True:
        topic, payload = SUB.recv(timeout_ms=500)
        if topic is None:
            continue
        try:
            msg = payload if isinstance(payload, dict) else json.loads(payload)
            if not isinstance(msg, dict):
                continue
            if not should_process(msg):
                continue

            text = (msg.get("text") or "").strip()
            if not text:
                continue

            cmd, _ = decide(text)
            if cmd:
                _bus_publish("motion.cmd", cmd)
                log(f"NLU → motion.cmd: {cmd}")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            log(f"NLU error: {e}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("NLU: bye")
