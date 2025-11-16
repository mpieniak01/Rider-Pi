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

PC_BASE_URL = os.getenv("PROVIDER_PC_BASE_URL", "http://127.0.0.1:8000")
PC_CAP_PATH = os.getenv("PROVIDER_PC_CAP_PATH", "/providers/capabilities")
CHECK_INTERVAL = float(os.getenv("PROVIDER_WATCHDOG_INTERVAL", "5.0"))
FAIL_THRESHOLD = int(os.getenv("PROVIDER_WATCHDOG_FAIL_THRESHOLD", "3"))
REQUEST_TIMEOUT = float(os.getenv("PROVIDER_WATCHDOG_TIMEOUT", "2.0"))
DISABLED = os.getenv("PROVIDER_WATCHDOG_DISABLED", "").lower() in {"1", "true", "yes"}

_thread: threading.Thread | None = None
_stop_event = threading.Event()
_lock = threading.Lock()


def _fetch_pc_capabilities() -> tuple[Any, float]:
    url = f"{PC_BASE_URL.rstrip('/')}{PC_CAP_PATH}"
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
    while not _stop_event.wait(CHECK_INTERVAL):
        try:
            data, latency_ms = _fetch_pc_capabilities()
            registry.update_pc_health(
                reachable=True,
                status="online",
                latency_ms=latency_ms,
                reason=data.get("version") if isinstance(data, dict) else "ok",
            )
            consecutive_failures = 0
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            consecutive_failures += 1
            registry.update_pc_health(
                reachable=False,
                status="offline",
                latency_ms=None,
                reason=str(exc)[:120],
            )
            LOG.warning("Provider watchdog failure (%d/%d): %s", consecutive_failures, FAIL_THRESHOLD, exc)
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
            LOG.error("Provider watchdog unexpected error: %s", exc)
            if consecutive_failures >= FAIL_THRESHOLD:
                _fallback_to_local("pc_error")

    LOG.info("Provider watchdog stopped")


def ensure_started() -> None:
    if DISABLED:
        LOG.info("Provider watchdog disabled via env")
        return
    global _thread
    with _lock:
        if _thread and _thread.is_alive():
            return
        _stop_event.clear()
        _thread = threading.Thread(target=_loop, name="provider-watchdog", daemon=True)
        _thread.start()


def stop() -> None:
    with _lock:
        if not _thread:
            return
        _stop_event.set()
        _thread.join(timeout=1.0)
