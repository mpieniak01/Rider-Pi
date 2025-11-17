#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from services import provider_registry as registry

LOG = logging.getLogger("provider_watchdog")

# Default PC base URL (fallback)
DEFAULT_PC_BASE_URL = "http://192.168.1.179:8000"

# Environment configuration
PC_BASE_URL = os.getenv("PROVIDER_PC_BASE_URL", "http://192.168.1.179:8000")
PC_CAP_PATH = os.getenv("PROVIDER_PC_CAP_PATH", "/providers/capabilities")
CHECK_INTERVAL = float(os.getenv("PROVIDER_WATCHDOG_INTERVAL", "5.0"))
FAIL_THRESHOLD = int(os.getenv("PROVIDER_WATCHDOG_FAIL_THRESHOLD", "3"))
REQUEST_TIMEOUT = float(os.getenv("PROVIDER_WATCHDOG_TIMEOUT", "2.0"))

HEARTBEAT_ONLY = os.getenv("PROVIDER_WATCHDOG_HEARTBEAT_ONLY", "").lower() in {
    "1",
    "true",
    "yes",
}
HEARTBEAT_TIMEOUT_MULTIPLIER = float(os.getenv("PROVIDER_WATCHDOG_HEARTBEAT_TIMEOUT_MULTIPLIER", "2.0"))
DISABLED = os.getenv("PROVIDER_WATCHDOG_DISABLED", "").lower() in {
    "1",
    "true",
    "yes",
}

_thread: threading.Thread | None = None
_stop_event = threading.Event()
_lock = threading.Lock()


def _fetch_pc_capabilities(base_url: str) -> tuple[Any, float]:
    url = f"{base_url.rstrip('/')}{PC_CAP_PATH}"
    req = urllib.request.Request(url, method="GET")
    start = time.time()

    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        raw = resp.read()
        latency_ms = (time.time() - start) * 1000.0

        if not raw:
            return {}, latency_ms

        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            data = {}

        return data, latency_ms


def _fallback_to_local(reason: str) -> None:
    for domain in registry.DOMAINS:
        try:
            state = registry.get_domain_state(domain)
            if state.get("mode") == "pc":
                registry.set_domain_mode(domain, "local", reason=reason)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("Watchdog fallback failed for %s: %s", domain, exc)


def _loop() -> None:
    LOG.info("Provider watchdog started (interval=%ss)", CHECK_INTERVAL)
    consecutive_failures = 0

    last_health_status: str | None = None

    while not _stop_event.wait(CHECK_INTERVAL):
        if HEARTBEAT_ONLY:
            consecutive_failures = _heartbeat_only_cycle(consecutive_failures)
            continue

        try:
            base_url = registry.get_pc_base_url()
            if not base_url:
                base_url = DEFAULT_PC_BASE_URL

            data, latency_ms = _fetch_pc_capabilities(base_url)

            registry.update_pc_health(
                reachable=True,
                status="online",
                latency_ms=latency_ms,
                reason=data.get("version") if isinstance(data, dict) else "ok",
            )
            last_health_status = "online"
            consecutive_failures = 0

        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            consecutive_failures += 1

            registry.update_pc_health(
                reachable=False,
                status="offline",
                latency_ms=None,
                reason=str(exc)[:120],
            )

            if last_health_status != "offline":
                LOG.warning(
                    "Provider watchdog failure (%d/%d): %s",
                    consecutive_failures,
                    FAIL_THRESHOLD,
                    exc,
                )
                last_health_status = "offline"

            if consecutive_failures >= FAIL_THRESHOLD:
                _fallback_to_local("pc_unreachable")

        except Exception as exc:  # noqa: BLE001
            consecutive_failures += 1

            registry.update_pc_health(
                reachable=False,
                status="error",
                latency_ms=None,
                reason=str(exc)[:120],
            )

            if last_health_status != "error":
                LOG.error("Provider watchdog unexpected error: %s", exc)
                last_health_status = "error"

            if consecutive_failures >= FAIL_THRESHOLD:
                _fallback_to_local("pc_error")

    LOG.info("Provider watchdog stopped")


def _heartbeat_only_cycle(consecutive_failures: int) -> int:
    """Evaluate reachability only based on incoming heartbeats."""
    snapshot = registry.get_health_snapshot()
    last_updated = snapshot.get("updated_ts") or 0.0
    elapsed = max(0.0, time.time() - last_updated)

    timeout = CHECK_INTERVAL * HEARTBEAT_TIMEOUT_MULTIPLIER

    if elapsed <= timeout:
        if snapshot.get("reachable") is not True:
            LOG.info("Provider watchdog heartbeat recovered (elapsed=%.1fs)", elapsed)

        registry.update_pc_health(
            reachable=True,
            status="online",
            reason="heartbeat",
        )
        return 0

    consecutive_failures += 1

    registry.update_pc_health(
        reachable=False,
        status="offline",
        reason="heartbeat_timeout",
    )

    LOG.warning(
        "Provider watchdog heartbeat timeout (%d/%d): %.1fs elapsed",
        consecutive_failures,
        FAIL_THRESHOLD,
        elapsed,
    )

    if consecutive_failures >= FAIL_THRESHOLD:
        _fallback_to_local("pc_unreachable")

    return consecutive_failures


def ensure_started() -> None:
    if DISABLED:
        LOG.info("Provider watchdog disabled via env")
        return

    global _thread
    with _lock:
        if _thread and _thread.is_alive():
            return

        _stop_event.clear()
        _thread = threading.Thread(
            target=_loop,
            name="provider-watchdog",
            daemon=True,
        )
        _thread.start()


def stop() -> None:
    with _lock:
        if not _thread:
            return

        _stop_event.set()
        _thread.join(timeout=1.0)
