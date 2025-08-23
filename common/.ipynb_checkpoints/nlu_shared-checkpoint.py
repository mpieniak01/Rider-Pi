#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
common/nlu_shared.py — wspólne funkcje NLU:
- norm()                 — normalizacja tekstu (lower, bez polskich znaków, proste literówki)
- is_motion_command()    — czy tekst wygląda na komendę ruchu
- parse_motion_intent()  — mapuje tekst na intent ruchu (dict) lub None
- confirm_text()         — krótka odpowiedź głosowa dla ruchu
"""

import re

ACCENT_MAP = str.maketrans("ąćęłńóśźż", "acelnoszz")

def norm(txt: str) -> str:
    t = (txt or "").lower()
    t = t.translate(ACCENT_MAP)
    t = re.sub(r"[^\w\s]+", " ", t)  # usuń interpunkcję/symbole
    t = re.sub(r"\s+", " ", t).strip()

# popularne literówki / warianty z ASR
    replacements = {
        "nerd gogle": "nerd google",
        "jezdz": "jedz",
        "jedzd": "jedz",

        # przód: różne warianty
        "idz do przodu": "do przodu",
        "naprzud": "naprzod",
        "do przod": "do przodu",
        "do przedu": "do przodu",
        "przedu": "przodu",
        "jedz do przod": "jedz do przodu",
        "jedz do przedu": "jedz do przodu",

        # NOWE: "na przód" → potraktuj jak "do przodu"
        "na przod": "do przodu",
        "na przodu": "do przodu",
        "jedz na przod": "jedz do przodu",
        "jedz na przodu": "jedz do przodu",
    }
    for a, b in replacements.items():
        t = t.replace(a, b)
    return t

# Wzorce komend ruchu
_PAT_STOP   = re.compile(r"\b(stop|stoj|zatrzymaj|przestan)\b")
# rozszerzone: dopuszczamy też bezpośrednio "na przod"
_PAT_FWD    = re.compile(r"\b(do przodu|na przod|naprzod|jedz(?: (?:do|na) przodu?)?|rusz)\b")
_PAT_BACK   = re.compile(r"\b(do tylu|wstecz|cofnij)\b")
_PAT_LEFT   = re.compile(r"\b(w lewo|skret w lewo|lewo)\b")
_PAT_RIGHT  = re.compile(r"\b(w prawo|skret w prawo|prawo)\b")
_PAT_SIT    = re.compile(r"\b(usiad|siad)\b")
_PAT_STAND  = re.compile(r"\b(wstan)\b")

def is_motion_command(text: str) -> bool:
    t = norm(text)
    return any((
        _PAT_STOP.search(t),
        _PAT_FWD.search(t),
        _PAT_BACK.search(t),
        _PAT_LEFT.search(t),
        _PAT_RIGHT.search(t),
        _PAT_SIT.search(t),
        _PAT_STAND.search(t),
    ))

def parse_motion_intent(text: str):
    """
    Zwraca dict intentu ruchu albo None:
      {"action":"forward|back|left|right|stop|sit|stand", "speed":..., "duration":...}
    """
    t = norm(text)

    if _PAT_STOP.search(t):
        return {"action": "stop"}

    if _PAT_FWD.search(t):
        return {"action": "forward", "speed": 0.5, "duration": 1.5}

    if _PAT_BACK.search(t):
        return {"action": "back", "speed": 0.5, "duration": 1.2}

    if _PAT_LEFT.search(t):
        return {"action": "left", "speed": 0.4, "duration": 0.8}

    if _PAT_RIGHT.search(t):
        return {"action": "right", "speed": 0.4, "duration": 0.8}

    if _PAT_SIT.search(t):
        return {"action": "sit"}

    if _PAT_STAND.search(t):
        return {"action": "stand"}

    return None

def confirm_text(intent: dict) -> str:
    a = intent.get("action")
    if a == "forward": return "Jadę do przodu."
    if a == "back":    return "Cofam."
    if a == "left":    return "Skręcam w lewo."
    if a == "right":   return "Skręcam w prawo."
    if a == "stop":    return "Zatrzymuję się."
    if a == "sit":     return "Siadam."
    if a == "stand":   return "Wstaję."
    return "Wykonuję polecenie."
