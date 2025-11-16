#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import os
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

try:
    from common import ai_mode
except ImportError:  # pragma: no cover - fallback for docs/tools
    ai_mode = None  # type: ignore

try:
    from common.bus import BusPub
except ImportError:  # pragma: no cover
    BusPub = None  # type: ignore

LOGGER = logging.getLogger("provider_registry")

DOMAINS: tuple[str, ...] = ("vision", "voice", "text")
DEFAULT_STATE_FILE = Path("data") / "providers_state.json"
STATE_FILE = Path(os.getenv("PROVIDER_STATE_FILE", str(DEFAULT_STATE_FILE)))
BUS_WARMUP_MS = int(os.getenv("PROVIDER_BUS_WARMUP_MS", "200") or "0")

_state_lock = threading.RLock()
_domains: dict[str, dict[str, Any]] = {}
_pc_health: dict[str, Any] = {
    "reachable": False,
    "status": "unknown",
    "latency_ms": None,
    "updated_ts": 0.0,
    "reason": "not_initialized",
}
_MISSING = object()
_bus_pub_lock = threading.Lock()
_bus_pub: BusPub | None = None


def _get_bus_pub() -> BusPub | None:
    global _bus_pub
    if _bus_pub:
        return _bus_pub
    if BusPub is None:
        return None
    with _bus_pub_lock:
        if _bus_pub is None:
            try:
                _bus_pub = BusPub(warmup_ms=BUS_WARMUP_MS)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Provider registry bus init failed: %s", exc)
                _bus_pub = None
        return _bus_pub


def _publish_provider_state_event(domain: str, state: dict[str, Any]) -> None:
    pub = _get_bus_pub()
    if not pub:
        return
    payload = dict(state)
    payload["domain"] = domain
    try:
        pub.publish(f"provider.{domain}.state", payload, add_ts=True)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Failed to publish provider.%s.state: %s", domain, exc)


def _sync_global_ai_mode(domains_snapshot: dict[str, dict[str, Any]]) -> None:
    if not ai_mode:
        return
    try:
        target = "pc_offload" if any(st.get("mode") == "pc" for st in domains_snapshot.values()) else "local"
        ai_mode.set_mode(target)  # set_mode already ignores when unchanged
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Provider registry failed to sync AI mode: %s", exc)


def _now() -> float:
    return time.time()


def _default_domain_state(reason: str = "default") -> dict[str, Any]:
    return {
        "mode": "local",
        "status": "local_only",
        "changed_ts": _now(),
        "reason": reason,
    }


def _ensure_defaults() -> None:
    for domain in DOMAINS:
        _domains.setdefault(domain, _default_domain_state("boot"))


def _load_state() -> None:
    if not STATE_FILE.exists():
        _ensure_defaults()
        return

    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for domain in DOMAINS:
                if isinstance(data.get(domain), dict):
                    state = data[domain]
                    _domains[domain] = {
                        "mode": state.get("mode", "local"),
                        "status": state.get("status", "local_only"),
                        "changed_ts": float(state.get("changed_ts", _now())),
                        "reason": state.get("reason", "load"),
                    }
        LOGGER.info("Provider registry state loaded from %s", STATE_FILE)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Failed to load provider state: %s", exc)
    finally:
        _ensure_defaults()


def _save_state() -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_domains, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("Failed to persist provider state: %s", exc)


def get_state_snapshot() -> dict[str, Any]:
    with _state_lock:
        return {
            "domains": deepcopy(_domains),
            "pc_health": deepcopy(_pc_health),
        }


def get_domain_state(domain: str) -> dict[str, Any]:
    domain = domain.lower()
    if domain not in DOMAINS:
        raise ValueError(f"Unknown domain: {domain}")
    with _state_lock:
        return deepcopy(_domains[domain])


def set_domain_mode(domain: str, target: str, *, reason: str = "manual") -> tuple[dict[str, Any], bool]:
    domain = domain.lower()
    if domain not in DOMAINS:
        raise ValueError(f"Unknown domain: {domain}")
    if target not in ("local", "pc"):
        raise ValueError("Target must be 'local' or 'pc'")

    with _state_lock:
        current = _domains[domain]
        if current["mode"] == target:
            return deepcopy(current), False

        new_state = dict(current)
        new_state["mode"] = target
        new_state["status"] = "pc_pending" if target == "pc" else "local_only"
        new_state["changed_ts"] = _now()
        new_state["reason"] = reason
        _domains[domain] = new_state
        snapshot = deepcopy(_domains)
        result = deepcopy(new_state)
        _save_state()
        LOGGER.info("Provider domain %s changed to %s (reason=%s)", domain, target, reason)
    _publish_provider_state_event(domain, result)
    _sync_global_ai_mode(snapshot)
    return result, True


def update_domain_status(domain: str, status: str, *, reason: str | None = None) -> dict[str, Any]:
    domain = domain.lower()
    if domain not in DOMAINS:
        raise ValueError(f"Unknown domain: {domain}")
    with _state_lock:
        state = _domains[domain]
        state["status"] = status
        if reason:
            state["reason"] = reason
        state["changed_ts"] = _now()
        snapshot = deepcopy(_domains)
        result = deepcopy(state)
        _save_state()
    _publish_provider_state_event(domain, result)
    _sync_global_ai_mode(snapshot)
    return result


def update_pc_health(
    *,
    reachable: bool | None = None,
    status: str | None = None,
    latency_ms: float | None | object = _MISSING,
    reason: str | None = None,
) -> dict[str, Any]:
    with _state_lock:
        if reachable is not None:
            _pc_health["reachable"] = bool(reachable)
        if status is not None:
            _pc_health["status"] = status
        if latency_ms is not _MISSING:
            _pc_health["latency_ms"] = latency_ms
        if reason:
            _pc_health["reason"] = reason
        _pc_health["updated_ts"] = _now()
        return deepcopy(_pc_health)


def get_health_snapshot() -> dict[str, Any]:
    with _state_lock:
        return deepcopy(_pc_health)


def reset_state() -> None:
    with _state_lock:
        _domains.clear()
        _ensure_defaults()
        _save_state()


# Initialize state on import
_ensure_defaults()
_load_state()
