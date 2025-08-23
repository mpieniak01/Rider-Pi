#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apps/chat/main.py — Chat: audio.transcript -> (OpenAI) -> tts.speak
Omija komendy ruchu (rozpoznaje je wspólną funkcją is_motion_command()).
"""

import os, sys, time, re

PROJ_ROOT = "/home/pi/robot"
if PROJ_ROOT not in sys.path:
    sys.path.insert(0, PROJ_ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

from common.bus import BusPub, BusSub, now_ts
from common.nlu_shared import is_motion_command

def log(msg):
    try:
        print(time.strftime("[%H:%M:%S]"), msg, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((time.strftime("[%H:%M:%S] ")+str(msg)+"\n").encode("utf-8","replace"))
        sys.stdout.flush()

# --- Fallback: jeśli brak OPENAI_API_KEY w env, spróbuj wczytać z profili powłoki ---
def _load_api_key_from_profiles() -> str:
    candidates = [
        os.path.expanduser("~/.bash_profile"),
        os.path.expanduser("~/.profile"),
        os.path.expanduser("~/.bashrc"),
    ]
    pat = re.compile(r'\s*export\s+OPENAI_API_KEY\s*=\s*["\']?([^"\']+)["\']?\s*')
    for p in candidates:
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    m = pat.match(line)
                    if m:
                        return m.group(1).strip()
        except Exception:
            continue
    return ""

# --- OpenAI client ---
try:
    from openai import OpenAI
except Exception as e:
    log(f"BLAD: brak pakietu openai: {e}")
    sys.exit(1)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or _load_api_key_from_profiles()
if not OPENAI_API_KEY:
    log("BLAD: OPENAI_API_KEY nie jest ustawiony. Uruchom 'source ~/.bash_profile' albo dodaj 'export OPENAI_API_KEY=...' do profilu.")
    sys.exit(1)

client = OpenAI(api_key=OPENAI_API_KEY)

PUB = BusPub()
SUB = BusSub("audio.transcript")

SYSTEM_PROMPT = (
    "Jesteś zwięzłym asystentem robota XGO. "
    "Odpowiadaj po polsku, jednym krótkim zdaniem."
)

def chat_answer(user_text: str) -> str:
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role":"system","content":SYSTEM_PROMPT},
            {"role":"user","content":user_text}
        ],
        temperature=0.3,
        max_tokens=80,
    )
    return resp.choices[0].message.content.strip()

def main():
    log("CHAT: start (sub audio.transcript -> pub tts.speak)")
    while True:
        topic, payload = SUB.recv(timeout_ms=500)
        if topic is None:
            continue
        text = (payload or {}).get("text", "").strip()
        if not text:
            continue

        # jeśli to komenda ruchu — zostaw to NLU/Motion
        if is_motion_command(text):
            log(f"CHAT: rozpoznano komendę ruchu, pomijam: {text!r}")
            continue

        try:
            ans = chat_answer(text)
            PUB.publish("tts.speak", {"text": ans, "ts": now_ts(), "source": "chat"})
            log(f"CHAT -> TTS: {ans}")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            log(f"CHAT: błąd: {e}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("CHAT: bye")
