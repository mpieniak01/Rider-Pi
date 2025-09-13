from __future__ import annotations
from flask import jsonify, request
from . import compat, chat_api

app = compat.app

def _jt(res):
    """Zamień tuple -> (jsonify,code) i popraw ts w historii (sekundy -> ms)."""
    if isinstance(res, tuple):
        body, code = res
    else:
        body, code = res, 200
    try:
        items = body.get("items")
        if isinstance(items, list):
            for it in items:
                ts = it.get("ts")
                if isinstance(ts, (int, float)) and ts < 1_000_000_000_000:
                    it["ts"] = int(ts * 1000)
    except Exception:
        pass
    return jsonify(body), code

def chat_history():
    limit = request.args.get("limit", 50, type=int)
    # spróbuj różnych nazw handlera historii
    for name in ("get_history", "history", "history_api"):
        fn = getattr(chat_api, name, None)
        if callable(fn):
            return _jt(fn(limit))
    return jsonify({"ok": True, "items": [], "limit": limit}), 200

def chat_send():
    payload = request.get_json(silent=True) or {}
    # obsłuż różne nazwy send()
    for name in ("post_send", "send", "send_message", "send_api"):
        fn = getattr(chat_api, name, None)
        if callable(fn):
            return _jt(fn(payload))
    return jsonify({"ok": False, "error": "no chat send handler"}), 500

# Rejestruj trasy tylko jeśli jeszcze nie istnieją
rules = {r.rule for r in app.url_map.iter_rules()}
if "/api/chat/history" not in rules:
    app.add_url_rule("/api/chat/history", view_func=chat_history, methods=["GET","OPTIONS"])
if "/api/chat/send" not in rules:
    app.add_url_rule("/api/chat/send", view_func=chat_send, methods=["POST","OPTIONS"])
