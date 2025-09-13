from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict, Any, List

from flask import request, jsonify

# Opcjonalny, docelowy magazyn historii – jeśli jest, użyjemy go.
try:
    from services.api_core import chat_store  # type: ignore
except Exception:  # brak lub inne API → przełącz na bufor in-memory
    chat_store = None  # type: ignore

# Prosty bufor na fallback (gdy nie ma chat_store)
_HISTORY: Deque[Dict[str, Any]] = deque(maxlen=200)


def _cors_headers() -> Dict[str, str]:
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    }


def chat_history():
    # Preflight
    if request.method == "OPTIONS":
        return ("", 204, _cors_headers())

    # Pobierz historię z magazynu, jeżeli dostępny; w przeciwnym wypadku z fallbacku
    if chat_store and hasattr(chat_store, "history"):
        try:
            items: List[Dict[str, Any]] = list(chat_store.history())  # oczekiwane API: iterator/lista dictów
        except Exception:
            items = list(_HISTORY)
    else:
        items = list(_HISTORY)

    # Obsługa limitu (?limit=50) – bierzemy najnowsze N
    try:
        limit = int(request.args.get("limit") or 0)
    except Exception:
        limit = 0
    if limit > 0:
        items = items[-limit:]

    return (jsonify({"ok": True, "items": items}), 200, _cors_headers())


def chat_send():
    # Preflight
    if request.method == "OPTIONS":
        return ("", 204, _cors_headers())

    data = request.get_json(silent=True) or {}
    msg = (data.get("msg") or "").strip()
    user = (data.get("user") or "user").strip()

    if not msg:
        return (jsonify({"ok": False, "error": "msg required"}), 400, _cors_headers())

    item = {"ts": time.time(), "user": user, "msg": msg}

    if chat_store:
        # Spróbuj użyć magazynu, ale nie wysypuj API jeśli coś jest inaczej.
        try:
            if hasattr(chat_store, "append"):
                chat_store.append(item)  # oczekiwane API
            elif hasattr(chat_store, "add"):
                chat_store.add(item)
            else:
                _HISTORY.append(item)
        except Exception:
            _HISTORY.append(item)
    else:
        _HISTORY.append(item)

    # Prosty echo – tu możesz podpiąć LLM / routing itp.
    return (jsonify({"ok": True, "echo": msg}), 200, _cors_headers())


def register(app) -> None:
    """
    Idempotentna rejestracja tras czatu.
    Trzymamy literalne ścieżki, żeby `grep '/api/chat'` je widział.
    """
    rules = {r.rule for r in app.url_map.iter_rules()}
    if "/api/chat/history" not in rules:
        app.add_url_rule("/api/chat/history", view_func=chat_history, methods=["GET", "OPTIONS"])
    if "/api/chat/send" not in rules:
        app.add_url_rule("/api/chat/send", view_func=chat_send, methods=["POST", "OPTIONS"])
    # Alias kompatybilności dla starszych frontów: POST /api/chat
    if "/api/chat" not in rules:
        app.add_url_rule("/api/chat", view_func=chat_send, methods=["POST", "OPTIONS"])
