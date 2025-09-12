from __future__ import annotations

import re
import time
from typing import Any

from .chat_store import append_msg, tail

MAX_LEN = 2000
USR_RE = re.compile(r"^[\w-]{1,32}$")


def send_message(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Validate and store a chat message."""
    msg = payload.get("msg")
    user = (payload.get("user") or "user").strip()
    if not isinstance(msg, str) or not msg.strip():
        return {"ok": False, "error": "msg required"}, 400
    if len(msg) > MAX_LEN:
        return {"ok": False, "error": f"msg too long (>{MAX_LEN})"}, 400
    if not USR_RE.match(user):
        return {"ok": False, "error": "bad user"}, 400
    clean = " ".join(msg.split())
    rec = {"ts": time.time(), "user": user, "msg": clean}
    append_msg(rec)
    return {"ok": True, "message": rec}, 200


def get_history(limit: int = 50) -> tuple[dict[str, Any], int]:
    """Return last N messages."""
    try:
        limit = int(limit)
    except Exception:
        return {"ok": False, "error": "bad limit"}, 400
    if not (1 <= limit <= 500):
        return {"ok": False, "error": "bad limit"}, 400
    return {"ok": True, "items": tail(limit)}, 200
