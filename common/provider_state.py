"""Lightweight accessors for provider registry state."""

from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

PROVIDER_DOMAINS: tuple[str, ...] = ("vision", "voice", "text")
STATE_FILE = Path(os.getenv("PROVIDER_STATE_FILE", "data/providers_state.json"))

_state_cache: dict[str, dict[str, Any]] = {}
_pc_health_cache: dict[str, Any] = {}
_cache_mtime: float = 0.0
_lock = threading.RLock()


def _default_state() -> dict[str, dict[str, Any]]:
    default_ts = 0.0
    return {
        domain: {
            "mode": "local",
            "status": "local_only",
            "changed_ts": default_ts,
            "reason": "default",
        }
        for domain in PROVIDER_DOMAINS
    }


def _load_state_locked() -> None:
    global _cache_mtime
    if not STATE_FILE.exists():
        _state_cache.update(_default_state())
        _pc_health_cache.clear()
        _cache_mtime = 0.0
        return

    try:
        mtime = STATE_FILE.stat().st_mtime
        if mtime == _cache_mtime and _state_cache:
            return
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        domains = data.get("domains") if isinstance(data, dict) else data
        if not isinstance(domains, dict):
            raise ValueError("invalid provider state format")
        new_state: dict[str, dict[str, Any]] = {}
        for domain in PROVIDER_DOMAINS:
            state = domains.get(domain) if isinstance(domains, dict) else None
            if isinstance(state, dict):
                new_state[domain] = {
                    "mode": state.get("mode", "local"),
                    "status": state.get("status", "local_only"),
                    "changed_ts": float(state.get("changed_ts", 0.0)),
                    "reason": state.get("reason", "cache"),
                }
            else:
                new_state[domain] = _default_state()[domain]
        _state_cache.clear()
        _state_cache.update(new_state)
        health = data.get("pc_health") if isinstance(data, dict) else {}
        _pc_health_cache.clear()
        if isinstance(health, dict):
            _pc_health_cache.update(health)
        _cache_mtime = mtime
    except Exception:
        _state_cache.clear()
        _state_cache.update(_default_state())
        _pc_health_cache.clear()
        _cache_mtime = 0.0


def get_state() -> dict[str, dict[str, Any]]:
    with _lock:
        _load_state_locked()
        return deepcopy(_state_cache)


def get_pc_health() -> dict[str, Any]:
    with _lock:
        _load_state_locked()
        return deepcopy(_pc_health_cache)


def get_domain_state(domain: str) -> dict[str, Any]:
    domain = domain.lower()
    if domain not in PROVIDER_DOMAINS:
        raise ValueError(f"Unknown provider domain: {domain}")
    with _lock:
        _load_state_locked()
        return deepcopy(_state_cache.get(domain) or _default_state()[domain])


def get_domain_mode(domain: str) -> str:
    return get_domain_state(domain).get("mode", "local")


def is_pc_mode(domain: str) -> bool:
    return get_domain_mode(domain) == "pc"
