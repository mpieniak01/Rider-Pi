"""Lightweight accessors for provider registry state."""

from __future__ import annotations

import json
import math
import os
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

PROVIDER_DOMAINS: tuple[str, ...] = ("vision", "voice", "text")
DOMAIN_ALIASES = {"asr": "voice", "tts": "voice"}
STATE_FILE = Path(os.getenv("PROVIDER_STATE_FILE", "data/providers_state.json"))

_state_cache: dict[str, dict[str, Any]] = {}
_pc_health_cache: dict[str, Any] = {}
_cache_mtime: object = None
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


def normalize_domain_state(state, *, reason="cache") -> dict[str, Any]:
    """One damaged domain cannot overwrite a separately repaired configuration."""
    changed = state.get("changed_ts") if isinstance(state, dict) else None
    if (
        isinstance(state, dict)
        and state.get("mode") in {"local", "pc"}
        and type(changed) in {int, float}
        and math.isfinite(changed)
    ):
        return {
            "mode": state["mode"],
            "status": state.get("status", "unknown"),
            "changed_ts": float(changed),
            "reason": state.get("reason", reason),
        }
    return {
        "mode": None,
        "status": "unknown",
        "changed_ts": None,
        "reason": "provider_state_invalid" if isinstance(state, dict) else "provider_domain_unconfigured",
    }


def _load_state_locked() -> None:
    global _cache_mtime
    if not STATE_FILE.exists():
        _state_cache.update(_default_state())
        _pc_health_cache.clear()
        _cache_mtime = 0.0
        return

    try:
        stat = STATE_FILE.stat()
        mtime = (str(STATE_FILE), stat.st_mtime_ns, stat.st_size, stat.st_ino)
        if mtime == _cache_mtime and _state_cache:
            return
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        domains = data.get("domains") if isinstance(data, dict) else data
        if not isinstance(domains, dict) and isinstance(data, dict):
            # backwards compatibility: file might contain plain domain map
            domains = data
        if not isinstance(domains, dict):
            raise ValueError("invalid provider state format")
        new_state: dict[str, dict[str, Any]] = {}
        for domain in PROVIDER_DOMAINS:
            new_state[domain] = normalize_domain_state(domains.get(domain))
        _state_cache.clear()
        _state_cache.update(new_state)
        health = data.get("pc_health") if isinstance(data, dict) else {}
        _pc_health_cache.clear()
        if isinstance(health, dict):
            _pc_health_cache.update(health)
        _cache_mtime = mtime
    except Exception:
        _state_cache.clear()
        _state_cache.update(
            {
                domain: {"mode": None, "status": "unknown", "changed_ts": None, "reason": "provider_state_invalid"}
                for domain in PROVIDER_DOMAINS
            }
        )
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
    domain = DOMAIN_ALIASES.get(domain.lower(), domain.lower())
    if domain not in PROVIDER_DOMAINS:
        raise ValueError(f"Unknown provider domain: {domain}")
    with _lock:
        _load_state_locked()
        return deepcopy(_state_cache.get(domain) or _default_state()[domain])


def get_domain_mode(domain: str) -> str | None:
    return get_domain_state(domain).get("mode")


def is_pc_mode(domain: str) -> bool:
    return get_domain_mode(domain) == "pc"
