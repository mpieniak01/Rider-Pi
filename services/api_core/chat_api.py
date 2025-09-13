from __future__ import annotations
from typing import Any, Dict, Tuple
from .chat_store import get_store

_MAX_MSG = 1000
_MAX_USER = 64

def _err(msg: str, code: int = 400) -> Tuple[Dict[str, Any], int]:
    return {"ok": False, "error": msg}, code

def send_api(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    payload = payload or {}
    msg = payload.get('msg','')
    if not isinstance(msg, str) or not msg.strip():
        return {'ok': False, 'error': 'msg required'}, 400
    if not isinstance(payload.get('user'), str) or not payload.get('user'):
        payload['user'] = 'web'

    # --- TS normalize (seconds -> ms) ---
    import time as _t
    ts = payload.get('ts')
    if isinstance(ts, (int, float)):
        payload['ts'] = int(ts*1000) if ts < 1_000_000_000_000 else int(ts)
    else:
        payload['ts'] = int(_t.time()*1000)
    # ts normalized above
    msg = (payload or {}).get('msg', '')
    if not isinstance(msg, str) or not msg.strip():
        return {'ok': False, 'error': 'msg required'}, 400
    # defaults
    if not isinstance(payload.get('user'), str) or not payload.get('user'):
        payload['user'] = 'api'
    # ts normalized above

    if not isinstance(payload, dict):
        return _err("bad json", 400)
    msg = str(payload.get("msg") or "").strip()
    user = str(payload.get("user") or "anon").strip() or "anon"
    if not msg:
        return _err("msg required", 400)
    if len(msg) > _MAX_MSG:
        return _err("msg too long", 400)
    if len(user) > _MAX_USER:
        return _err("user too long", 400)
    item = get_store().add(msg=msg, user=user)
    return {"ok": True, "item": item}, 200

def history_api(limit: int | None) -> Tuple[Dict[str, Any], int]:
    try:
        n = int(limit if limit is not None else 20)
    except Exception:
        return _err("bad limit", 400)
    n = max(1, min(200, n))
    items = get_store().list(limit=n, newest_first=True)
    return {"ok": True, "items": items, "count": len(items)}, 200
