from __future__ import annotations
import json
from flask import jsonify
from services.api_core import compat
from services.api_core.vision_api import load_obstacle  # reużywamy jednej logiki

def state_route():
    """
    Deleguje do compat.state() i dokleja vision.obstacle (jeśli dostępne),
    zachowując kod HTTP i ciało bazowe.
    """
    base_resp = compat.state()
    status = getattr(base_resp, "status_code", 200)

    payload = None
    get_json = getattr(base_resp, "get_json", None)
    if callable(get_json):
        payload = base_resp.get_json(silent=True)
    if payload is None:
        try:
            payload = json.loads(base_resp.get_data(as_text=True) or "{}")
        except Exception:
            payload = {}

    obst = load_obstacle()
    if obst:
        payload.setdefault("vision", {})["obstacle"] = obst

    return jsonify(payload), status
