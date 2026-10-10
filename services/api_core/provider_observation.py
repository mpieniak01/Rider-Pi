"""Provider configuration and observed backend capability are distinct facts."""

from __future__ import annotations

import math
import time

from common import systemd_ctrl, task_runtime
from services import provider_registry as registry


def _source_fresh(value, now, max_age_s=3.0):
    return type(value) in {int, float} and math.isfinite(value) and -0.1 <= now - value <= max_age_s


def _real(row):
    return (
        row.get("simulated") is not True
        and row.get("source") not in {"demo", "mock", "simulation", "echo"}
        and row.get("stale") is not True
        and row.get("offline") is not True
        and not row.get("error")
    )


def _local(domain, worker, unit, now):
    names = ("asr", "tts") if domain == "voice" else ("chat",) if domain == "text" else ()
    capabilities = worker.get("capabilities", {})
    if not isinstance(capabilities, dict):
        capabilities = {}
    pid_matches = type(unit.get("pid")) is int and unit["pid"] > 0 and worker.get("pid") == unit["pid"]
    fresh = (
        _real(worker)
        and _source_fresh(worker.get("observed_at"), now)
        and unit.get("active", unit.get("active_state")) == "active"
        and unit.get("stale") is not True
        and not unit.get("error")
        and pid_matches
    )
    selected = {name: capabilities.get(name, {}) for name in names}
    selected_domains = worker.get("domains")
    selected_current = isinstance(selected_domains, list) and all(name in selected_domains for name in names)
    ready = (
        bool(names)
        and fresh
        and selected_current
        and all(
            isinstance(row, dict)
            and _real(row)
            and row.get("ready") is True
            and (name == "chat" or row.get("model_loaded") is True)
            for name, row in selected.items()
        )
    )
    return {
        "backend": selected.get("chat", {}).get("backend") if domain == "text" else domain,
        "host": "pi",
        "initialized": fresh and selected_current and bool(names),
        "model_loaded": all(isinstance(row, dict) and row.get("model_loaded") is True for row in selected.values())
        if selected
        else None,
        "ready": ready,
        "capabilities": selected,
        "source": "voice-worker" if names else "unknown",
        "observed_at": worker.get("observed_at") if names else None,
        "error": None if ready else "backend_not_ready" if names else "provider_observation_unavailable",
    }


def snapshot(*, worker=None, unit=None, now=None) -> dict:
    now = time.time() if now is None else now
    state = registry.get_state_snapshot()
    health = registry.get_health_snapshot()
    worker = task_runtime.read_status("rider-voice-web.service") if worker is None else worker
    unit = systemd_ctrl.status("rider-voice-web.service") if unit is None else unit
    domains = {}
    for domain, configured in state["domains"].items():
        if configured.get("mode") == "pc":
            capabilities = health.get("capabilities")
            row = capabilities.get(domain, {}) if isinstance(capabilities, dict) else {}
            row = row if isinstance(row, dict) else {}
            observed = row.get("observed_at")
            source_fresh = _source_fresh(observed, now, 10)
            ready = (
                health.get("reachable") is True
                and health.get("stale") is not True
                and source_fresh
                and row.get("initialized") is True
                and row.get("ready") is True
                and _real(row)
            )
            backend = {
                **row,
                "ready": ready,
                "host": "pc",
                "source": row.get("source", "unknown"),
                "error": row.get("error") or (None if ready else "peer_backend_unavailable"),
            }
        elif configured.get("mode") == "local":
            backend = _local(domain, worker, unit, now)
        else:
            backend = {
                "ready": False,
                "initialized": False,
                "backend": None,
                "host": None,
                "source": "unknown",
                "observed_at": None,
                "error": "provider_domain_unconfigured",
            }
        domains[domain] = {
            **configured,
            "domain": domain,
            "requested": configured.get("mode"),
            "effective": configured.get("mode") if backend.get("ready") is True else "unavailable",
            "configured": configured.get("mode") in {"local", "pc"},
            "persisted": state["persisted"],
            "backend_state": backend,
            "ready": backend.get("ready") is True,
            "initialized": backend.get("initialized") is True,
            "model_loaded": backend.get("model_loaded"),
            "backend": backend.get("backend"),
            "host": backend.get("host"),
            "observed_at": backend.get("observed_at"),
            "source": backend.get("source"),
            "error": backend.get("error"),
        }
    return {
        **state,
        "domains": domains,
        "pc_health": health,
        "partial": any(not row["ready"] for row in domains.values()),
        "domain_aliases": {"asr": "voice", "tts": "voice"},
    }
