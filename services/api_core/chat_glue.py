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
    """
    Lokalny agent został przeniesiony do apps/voice/web.py jako /api/chat endpoint.
    Użyj CHAT_REMOTE_URL=http://127.0.0.1:8092/api/chat aby połączyć się z lokalnym LLM.
    """
    return False, ""


def _reply_candidates(payload):
    candidates = [payload.get(key) for key in ("reply", "text", "content")]
    message = payload.get("message")
    candidates.append(message.get("content") if isinstance(message, dict) else message)
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        candidates.append(message.get("content") if isinstance(message, dict) else None)
    return candidates


def _payload_reply(payload):
    if not isinstance(payload, dict) or ("ok" in payload and payload["ok"] is not True) or payload.get("error"):
        return False, "remote_backend_error", "unavailable"
    source = payload.get("source") or payload.get("backend") or "remote"
    if (
        not isinstance(source, str)
        or source.strip().lower() in {"echo", "mock", "demo", "stub", "fallback", "simulated"}
        or any(payload.get(flag) is True for flag in ("demo", "mock", "simulated"))
    ):
        return False, "remote_demo_or_echo", "unavailable"
    candidates = _reply_candidates(payload)
    text = next((item.strip() for item in candidates if isinstance(item, str) and item.strip()), None)
    if text is None:
        return False, "remote_empty_reply", "unavailable"
    return True, text, source.strip()


def _remote_reply(prompt: str) -> tuple[bool, str, str]:
    """Use explicit or selected backend; preserve truthful result provenance."""
    url = os.getenv("CHAT_REMOTE_URL", "").strip()
    if not url:
        from .text_profile import selected_endpoint

        url = selected_endpoint()
    if not url:
        return False, "ai_backend_unavailable", "unavailable"
    try:
        import urllib.request

        req = urllib.request.Request(
            url,
            data=json.dumps({"text": prompt, "messages": [{"role": "user", "content": prompt}]}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:  # nosec - configured backend URL
            if resp.status >= 400:
                return False, f"remote_http_{resp.status}", "unavailable"
            raw = resp.read(1048577)
            if len(raw) > 1048576:
                return False, "remote_reply_too_large", "unavailable"
            payload = json.loads(raw.decode("utf-8") or "{}")
            return _payload_reply(payload)

    except Exception as exc:  # noqa: BLE001
        return False, f"remote_error: {exc}", "unavailable"


def _try_remote_api(prompt: str) -> tuple[bool, str]:
    """Compatibility helper retains its original two-value result."""
    ok, text, _source = _remote_reply(prompt)
    return ok, text


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

    from apps.compute.client import ComputeError
    from services import compute_config
    from services.compute_operations import execute

    try:
        selected = compute_config.selected_executor()
        if selected is not None:
            result, _ = execute(
                "text.respond",
                msg.encode("utf-8"),
                "text/plain; charset=utf-8",
                {"language": payload.get("language", "pl")},
            )
            reply = result.get("data", {}).get("text", "")
            _store_add({"user": user, "msg": msg})
            _store_add({"user": "bot", "msg": reply, "source": selected["id"]})
            return jsonify({"ok": True, "reply": reply, "source": selected["id"], "observation": result}), 200
    except ComputeError as exc:
        return jsonify({"ok": False, "error": exc.code}), exc.status if 400 <= exc.status <= 599 else 503
    except (ValueError, OSError):
        return jsonify({"ok": False, "error": "compute_configuration_unavailable"}), 503

    # zapisujemy wejście
    _store_add({"user": user, "msg": msg})

    ok, text = _try_local_agent(msg)
    source = "local"
    backend_error = None
    if not ok:
        ok, text, source = _remote_reply(msg)
    if not ok:
        backend_error, text, source = text, msg, "echo"

    _store_add({"user": "bot", "msg": text, "source": source})
    return jsonify(
        {
            "ok": ok,
            "reply": text,
            "source": source,
            "error": None if ok else "ai_backend_unavailable",
            "backend_error": backend_error,
        }
    ), 200 if ok else 503


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
