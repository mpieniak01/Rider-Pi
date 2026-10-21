#!/usr/bin/env python3
from __future__ import annotations

import ipaddress
import json
import logging
import math
import os
import tempfile
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from common.compute_url import validate_transport_profile
from common.provider_state import normalize_domain_state

try:
    from common.bus import BusPub
except ImportError:  # pragma: no cover
    BusPub = None  # type: ignore

LOGGER = logging.getLogger("provider_registry")

DOMAINS: tuple[str, ...] = ("vision", "voice", "text")
DEFAULT_STATE_FILE = Path("data") / "providers_state.json"
STATE_FILE = Path(os.getenv("PROVIDER_STATE_FILE", str(DEFAULT_STATE_FILE)))
BUS_WARMUP_MS = int(os.getenv("PROVIDER_BUS_WARMUP_MS", "200") or "0")
DEFAULT_PC_BASE_URL = os.getenv("PROVIDER_PC_BASE_URL", "http://127.0.0.1:8000")

_state_lock = threading.RLock()
_domains: dict[str, dict[str, Any]] = {}
_pc_health: dict[str, Any] = {
    "reachable": False,
    "status": "unknown",
    "latency_ms": None,
    "updated_ts": 0.0,
    "reason": "not_initialized",
}
_pc_base_url: str = DEFAULT_PC_BASE_URL
_MISSING = object()
_bus_pub_lock = threading.Lock()
_bus_pub: BusPub | None = None
_load_error: str | None = None


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
    global _load_error
    if not STATE_FILE.exists():
        _ensure_defaults()
        return

    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("provider state must be an object")
        if isinstance(data, dict):
            domains_raw = data.get("domains")
            if isinstance(domains_raw, dict):
                sources = domains_raw
            else:
                sources = data
            for domain in DOMAINS:
                _domains[domain] = normalize_domain_state(sources.get(domain), reason="load")
            _load_error = None
            health = data.get("pc_health")
            if isinstance(health, dict):
                _pc_health.clear()
                _pc_health.update(
                    {
                        "reachable": health.get("reachable") is True,
                        "status": health.get("status", "unknown"),
                        "latency_ms": health.get("latency_ms"),
                        "updated_ts": float(health.get("updated_ts", 0.0)),
                        "reason": health.get("reason", "load"),
                        "observed_at": health.get("observed_at"),
                        "received_at": health.get("received_at"),
                        "capabilities": health.get("capabilities"),
                    }
                )
            base_url = data.get("pc_base_url")
            if isinstance(base_url, str) and base_url.strip():
                global _pc_base_url
                _pc_base_url = base_url.strip()
        LOGGER.info("Provider registry state loaded from %s", STATE_FILE)
    except Exception as exc:  # noqa: BLE001
        _load_error = "provider_state_invalid"
        _domains.clear()
        _domains.update(
            {
                domain: {"mode": None, "status": "unknown", "changed_ts": None, "reason": _load_error}
                for domain in DOMAINS
            }
        )
        LOGGER.warning("Failed to load provider state: %s", exc)
    finally:
        _ensure_defaults()


def _save_state() -> None:
    global _load_error
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "domains": deepcopy(_domains),
        "pc_health": deepcopy(_pc_health),
        "pc_base_url": _pc_base_url,
    }
    fd, name = tempfile.mkstemp(prefix=".providers-", dir=STATE_FILE.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, STATE_FILE)
        # Unknown domains remain explicit in their own rows. A successfully
        # persisted registry is readable even while another domain needs repair.
        _load_error = None
    finally:
        try:
            os.unlink(name)
        except OSError:
            pass


def get_state_snapshot() -> dict[str, Any]:
    with _state_lock:
        return {
            "domains": deepcopy(_domains),
            "pc_health": deepcopy(_pc_health),
            "pc_base_url": _pc_base_url,
            "source": "provider-registry",
            "observed_at": None,
            "persisted": STATE_FILE.is_file(),
            "error": _load_error,
        }


def get_domain_state(domain: str) -> dict[str, Any]:
    domain = domain.lower()
    if domain not in DOMAINS:
        raise ValueError(f"Unknown domain: {domain}")
    with _state_lock:
        return deepcopy(_domains[domain])


def _validated_reason(value: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 256 or not value.strip() or not value.isprintable():
        raise ValueError("invalid_provider_reason")
    return value


def set_domain_mode(domain: str, target: str, *, reason: str = "manual") -> tuple[dict[str, Any], bool]:
    reason = _validated_reason(reason)
    domain = domain.lower()
    if domain not in DOMAINS:
        raise ValueError(f"Unknown domain: {domain}")
    if target not in ("local", "pc"):
        raise ValueError("Target must be 'local' or 'pc'")

    with _state_lock:
        current = _domains[domain]
        if current["mode"] == target:
            if not STATE_FILE.is_file():
                _save_state()
            return deepcopy(current), False

        new_state = dict(current)
        new_state["mode"] = target
        new_state["status"] = "pc_pending" if target == "pc" else "local_only"
        new_state["changed_ts"] = _now()
        new_state["reason"] = reason
        _domains[domain] = new_state
        try:
            _save_state()
        except (OSError, ValueError):
            _domains[domain] = current
            raise
        result = deepcopy(new_state)
        LOGGER.info("Provider domain %s changed to %s (reason=%r)", domain, target, reason)
    _publish_provider_state_event(domain, result)
    return result, True


def set_all_domain_modes(target: str, *, reason: str = "legacy_global") -> tuple[dict, bool]:
    """Only the explicit legacy global operation changes all domains atomically."""
    if target not in {"local", "pc"}:
        raise ValueError("invalid provider mode")
    with _state_lock:
        previous = deepcopy(_domains)
        changed = any(row.get("mode") != target for row in _domains.values())
        for row in _domains.values():
            if row.get("mode") != target:
                row.update(
                    mode=target,
                    status="pc_pending" if target == "pc" else "local_only",
                    changed_ts=_now(),
                    reason=reason,
                )
        try:
            _save_state()
        except (OSError, ValueError):
            _domains.clear()
            _domains.update(previous)
            raise
        result = deepcopy(_domains)
    for domain, row in result.items():
        _publish_provider_state_event(domain, row)
    return result, changed


def update_domain_status(domain: str, status: str, *, reason: str | None = None) -> dict[str, Any]:
    domain = domain.lower()
    if domain not in DOMAINS:
        raise ValueError(f"Unknown domain: {domain}")
    with _state_lock:
        previous = deepcopy(_domains[domain])
        state = dict(previous)
        state["status"] = status
        if reason:
            state["reason"] = reason
        state["changed_ts"] = _now()
        _domains[domain] = state
        try:
            _save_state()
        except (OSError, ValueError):
            _domains[domain] = previous
            raise
        result = deepcopy(state)
    _publish_provider_state_event(domain, result)
    return result


def update_pc_health(
    *,
    reachable: bool | None = None,
    status: str | None = None,
    latency_ms: float | None | object = _MISSING,
    reason: str | None = None,
    observed_at: float | None | object = _MISSING,
    received_at: float | None | object = _MISSING,
    capabilities: dict | object = _MISSING,
    refresh: bool = True,
) -> dict[str, Any]:
    with _state_lock:
        previous = deepcopy(_pc_health)
        if reachable is not None:
            _pc_health["reachable"] = bool(reachable)
        if status is not None:
            _pc_health["status"] = status
        if latency_ms is not _MISSING:
            _pc_health["latency_ms"] = latency_ms
        if reason:
            _pc_health["reason"] = reason
        if refresh:
            _pc_health["updated_ts"] = _now()
        if observed_at is not _MISSING:
            _pc_health["observed_at"] = observed_at
        if received_at is not _MISSING:
            _pc_health["received_at"] = received_at
        if capabilities is not _MISSING:
            _pc_health["capabilities"] = deepcopy(capabilities)
        snapshot = deepcopy(_pc_health)
        try:
            _save_state()
        except (OSError, ValueError):
            _pc_health.clear()
            _pc_health.update(previous)
            raise
        return snapshot


def get_health_snapshot() -> dict[str, Any]:
    with _state_lock:
        result = deepcopy(_pc_health)
    received = result.get("received_at", result.get("updated_ts"))
    age = _now() - received if type(received) in {int, float} and math.isfinite(received) else None
    result.update(
        source="pc-heartbeat",
        stale=age is None or not -0.1 <= age <= 10,
        offline=result.get("reachable") is not True,
        transport={"received_at": received},
        observed_at=result.get("observed_at"),
    )
    return result


def get_pc_base_url() -> str:
    with _state_lock:
        return _peer_url(_pc_base_url or DEFAULT_PC_BASE_URL)


def get_pc_transport_options():
    """Legacy routing has its own explicit binding; compute selection stays authoritative."""
    profile = os.getenv("PROVIDER_PC_TRANSPORT_PROFILE", "secure")
    peer_id = os.getenv("PROVIDER_PC_EXPECTED_PEER_ID") or None
    validate_transport_profile(profile, peer_id)
    return {"transport_profile": profile, "expected_peer_id": peer_id}


def _peer_url(base_url: str) -> str:
    """Legacy HTTP uses the same explicit peer profile as current compute."""
    options = get_pc_transport_options()
    if not isinstance(base_url, str) or not base_url or any(char.isspace() or ord(char) < 32 for char in base_url):
        raise ValueError("invalid_peer_url")
    parsed = urlsplit(base_url if "://" in base_url else "//" + base_url)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or "\\" in base_url:
        raise ValueError("invalid_peer_url")
    try:
        loopback = parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        loopback = False
    scheme = parsed.scheme or ("http" if loopback else "https")
    if scheme not in {"http", "https"} or (
        scheme == "http" and not loopback and options["transport_profile"] != "trusted_lan"
    ):
        raise ValueError("remote_provider_requires_https")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("invalid_peer_port")
    return urlunsplit((scheme, parsed.netloc, parsed.path, "", ""))


def set_pc_base_url(base_url: str, *, reason: str = "manual") -> str:
    reason = _validated_reason(reason)
    normalized = (base_url or "").strip()
    if not normalized:
        raise ValueError("base_url must be non-empty")
    target = _peer_url(normalized)
    global _pc_base_url
    with _state_lock:
        if target == _pc_base_url:
            return _pc_base_url
        previous = _pc_base_url
        _pc_base_url = target.rstrip("/")
        try:
            _save_state()
        except (OSError, ValueError):
            _pc_base_url = previous
            raise
    LOGGER.info("PC base URL updated to %r (reason=%r)", _pc_base_url, reason)
    return _pc_base_url


def record_pc_heartbeat(base_url: str, payload: dict) -> str:
    """Persist address and transport heartbeat as a single transaction."""
    from urllib.parse import urlsplit

    target = _peer_url(base_url.strip().rstrip("/"))
    parsed = urlsplit(target)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("invalid peer base_url")
    observed = payload.get("observed_at")
    if observed is not None and (type(observed) not in {int, float} or not math.isfinite(observed) or observed <= 0):
        raise ValueError("invalid peer observed_at")
    capabilities = payload.get("capabilities")
    if capabilities is not None and not isinstance(capabilities, dict):
        raise ValueError("invalid peer capabilities")
    global _pc_base_url
    with _state_lock:
        if get_pc_transport_options()["transport_profile"] == "trusted_lan" and target != _pc_base_url:
            # A heartbeat cannot rebind a configured LAN peer or replace its hostname with an IP.
            raise ValueError("legacy_peer_binding_mismatch")
        previous_url, previous_health = _pc_base_url, deepcopy(_pc_health)
        _pc_base_url = target
        _pc_health.update(
            reachable=True,
            status="online",
            reason=payload.get("reason", "heartbeat"),
            observed_at=observed,
            updated_ts=_now(),
            received_at=_now(),
            capabilities=capabilities,
        )
        try:
            _save_state()
        except (OSError, ValueError):
            _pc_base_url = previous_url
            _pc_health.clear()
            _pc_health.update(previous_health)
            raise
    return target


def reset_state() -> None:
    with _state_lock:
        _domains.clear()
        _ensure_defaults()
        _save_state()


# Initialize state on import
_ensure_defaults()
_load_state()
