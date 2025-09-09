#!/usr/bin/env python3
# Zwraca bieżący wynik detekcji przeszkody (obstacle.json), jeśli istnieje.
import os, json, time
from flask import jsonify, Response

DATA_DIR = os.environ.get("DATA_DIR", "/home/pi/robot/data")
OBST_JSON = os.path.join(DATA_DIR, "obstacle.json")

def obstacle_get():
    now = time.time()
    payload = {
        "type": "obstacle", "present": False, "confidence": 0.0,
        "edge_pct": 0.0, "edge_nz": 0,
        "roi": {"y0": None, "y1": None, "w": None, "h": None},
        "ts": None, "age_s": None
    }
    try:
        with open(OBST_JSON, "r") as f:
            obj = json.load(f)
        payload.update(obj)
        if obj.get("ts"):
            payload["age_s"] = now - float(obj["ts"])
    except Exception:
        pass
    return jsonify(payload)