# services/api_core/chat_glue.py
from __future__ import annotations

import json
import os
import time
from collections import deque
from typing import Any

from flask import jsonify, request

# Opcjonalny magazyn historii – jeśli jest, użyjemy go. Inaczej bufor w pamięci.
try:
    from services.api_core import chat_store  # type: ignore
except Exception:
    chat_store = None  # type: ignore

# Prosty bufor fallback (gdy nie ma chat_store)
_HISTORY: deque[dict[str, Any]] = deque(maxlen=200)


def _store_add(item: dict[str, Any]) -> dict[str, Any]:
    """Dodaj wpis do historii (store lub pamięć). Zwróć to co zapisano."""
    item.setdefault("ts", time.time())
    if chat_store is not None and hasattr(chat_store, "add_item"):
        try:
            return chat_store.add_item(item)  # type: ignore[attr-defined]
        except Exception:
            pass
    # fallback: pamięć
    _HISTORY.append(item)
    return item


def _store_list(limit: int | None = None, newest_first: bool = False) -> list[dict[str, Any]]:
    """Pobierz historię (store lub pamięć)."""
    # chat_store.history() zwraca starsze→nowsze
    if chat_store is not None and hasattr(chat_store, "history"):
        try:
            data_all = list(chat_store.history(None))  # type: ignore[attr-defined]
        except Exception:
            data_all = list(_HISTORY)
    else:
        data_all = list(_HISTORY)

    if limit is None or limit <= 0:
        data = data_all
    else:
        data = data_all[-limit:]

    if newest_first:
        data.reverse()
    return data


# ── AGENT: lokalny → zdalny → echo ───────────────────────────────────────────
def _try_local_agent(prompt: str) -> tuple[bool, str]:
    """Spróbuj lokalnego agenta jeśli dostępny: services.api_core.local_chat.ask(text)->str"""
    try:
        from services.api_core import local_chat  # type: ignore

        ask = getattr(local_chat, "ask", None)
        if callable(ask):
            text = str(ask(prompt))
            if text.strip():
                return True, text
    except Exception:
        pass
    return False, ""


def _try_remote_api(prompt: str) -> tuple[bool, str]:
    """Jeśli ustawione CHAT_REMOTE_URL, wyślij POST JSON {text}. Bez zewn. zależności."""
    url = os.getenv("CHAT_REMOTE_URL", "").strip()
    if not url:
        return False, ""
    try:
        import urllib.request

        req = urllib.request.Request(
            url,
            data=json.dumps({"text": prompt}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:  # nosec - kontrolowany URL z env
            if resp.status >= 400:
                return False, f"remote_http_{resp.status}"
            payload = json.loads(resp.read().decode("utf-8") or "{}")
            # akceptuj różne klucze
            text = (
                payload.get("reply")
                or payload.get("text")
                or payload.get("message")
                or payload.get("content")
                or (
                    payload.get("choices", [{}])[0].get("message", {}).get("content")
                    if isinstance(payload.get("choices"), list)
                    else None
                )
                or ""
            )
            if str(text).strip():
                return True, str(text)
            # jeśli nie ma treści, zwróć cały JSON
            return True, json.dumps(payload, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001
        return False, f"remote_error: {e}"


# ── HANDLERY HTTP ────────────────────────────────────────────────────────────
def chat_history():
    if request.method == "OPTIONS":
        return jsonify(""), 204
    limit_raw = request.args.get("limit")
    try:
        limit = int(limit_raw) if limit_raw is not None else None
    except Exception:
        limit = None
    items = _store_list(limit=limit, newest_first=False)
    return jsonify({"ok": True, "items": items}), 200


def chat_send():
    if request.method == "OPTIONS":
        return jsonify(""), 204

    payload = request.get_json(silent=True) or {}
    msg = str(payload.get("msg") or payload.get("text") or "").strip()
    user = str(payload.get("user") or "web").strip()
    if not msg:
        return jsonify({"ok": False, "error": "empty_msg"}), 400

    # zapisujemy wejście
    _store_add({"user": user, "msg": msg})

    # 1) lokalny agent
    ok, text = _try_local_agent(msg)
    # 2) zdalne API (jeśli brak lub fail lokalnego)
    if not ok:
        ok, text2 = _try_remote_api(msg)
        if ok:
            text = text2

    if not ok:
        # 3) fallback: echo
        text = msg

    # zapisujemy odpowiedź bota
    _store_add({"user": "bot", "msg": text})
    return jsonify({"ok": True, "reply": text, "source": ("local" if ok else "echo")}), 200


# ── Rejestracja tras ─────────────────────────────────────────────────────────
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
