"""Observed task state, moved from the orchestrator without changing imports."""

from __future__ import annotations

import json
import time

from apps.voice.domain_profiles import expand
from common.service_catalog import (
    CONTRACT_VERSION,
    UNIT_CATALOG,
    catalog_payload,
    option_schema,
    task_domain,
    task_resources,
    task_units,
)

MOVING_PRODUCERS = {"rider-tracking-controller.service", "rider-navigator.service"}


class FeatureStateMixin:
    @staticmethod
    def _requires_producer(feature, units) -> bool:
        return bool(set(units) & MOVING_PRODUCERS or "rider-voice-web.service" in units)

    def _producer_readiness(self, feature, units, options) -> tuple[bool, list[dict]]:
        statuses = []
        accepted = True
        for unit in set(units) & MOVING_PRODUCERS:
            status = self.producer_status(unit)
            intent = self._intents.get(feature.name, {})
            valid = (
                status.get("accepted") is True
                and status.get("active") is True
                and status.get("stale") is not True
                and status.get("generation") == intent.get("generation")
                and status.get("request_id") == intent.get("request_id")
                and bool(intent.get("request_id"))
            )
            observed_unit = self._status(unit)
            if "pid" in observed_unit:
                observed_pid = observed_unit["pid"]
                valid = valid and isinstance(observed_pid, int) and not isinstance(observed_pid, bool)
                valid = valid and observed_pid > 0 and status.get("pid") == observed_pid
            accepted = accepted and valid
            statuses.append({**status, "matches_task": valid})
        if "rider-voice-web.service" in units:
            status = self.producer_status("rider-voice-web.service")
            domains = expand(task_domain(feature, options))
            capabilities = status.get("capabilities", {})
            observed_domains = status.get("domains")
            valid = (
                status.get("stale") is not True
                and isinstance(observed_domains, list)
                and all(isinstance(domain, str) for domain in observed_domains)
                and domains <= set(observed_domains)
                and isinstance(capabilities, dict)
                and all(
                    isinstance(capabilities.get(domain), dict)
                    and capabilities[domain].get("ready") is True
                    and (domain == "chat" or capabilities[domain].get("model_loaded") is True)
                    for domain in domains
                )
            )
            observed_unit = self._status("rider-voice-web.service")
            if "pid" in observed_unit:
                observed_pid = observed_unit["pid"]
                valid = valid and isinstance(observed_pid, int) and not isinstance(observed_pid, bool)
                valid = valid and observed_pid > 0 and status.get("pid") == observed_pid
            accepted = accepted and valid
            statuses.append({**status, "matches_task": valid})
        return accepted, statuses

    def _describe(self, name: str) -> dict:
        feature = self.registry[name]
        requested = name in self._requested or name in self._pending
        options = self._requested.get(name, self._pending.get(name, {}))
        units = task_units(feature, options)
        services = []
        for unit in units:
            row = self._status(unit)
            services.append(
                {
                    **row,
                    "active": row.get("active") == "active",
                    "active_state": row.get("active"),
                    "installed": row.get("load", "loaded") == "loaded" and not row.get("error"),
                    "consumers": self.unit_consumers(unit),
                    "can_move": UNIT_CATALOG.get(unit, {}).get("can_move", False),
                }
            )
        installed = all(row["installed"] for row in services)
        running = installed and all(row["active"] for row in services)
        permitted = self._permission(feature) is None
        baseline_safety = self.safety_status() if name == "s0_core" else None
        if baseline_safety is not None:
            permitted = baseline_safety.get("ready") is True and baseline_safety.get("stale") is not True
        intent = self._intents.get(name, {})
        if feature.can_move and requested:
            permitted = permitted and intent.get("generation") == self.safety_status().get("generation")
        accepted, producers = self._producer_readiness(feature, units, options) if requested else (True, [])
        state = self._states.get(name, "stopped")
        if requested and state == "starting" and running and permitted and accepted:
            state = "ready"
        elif (
            requested
            and state == "starting"
            and (
                not permitted
                or time.monotonic() - self._started_at.get(name, time.monotonic()) >= 5
                or any(status.get("stale") is not True and status.get("missing") for status in producers)
            )
        ):
            state = "partial"
        elif requested and state not in {"starting", "stopping", "failed", "partial"}:
            state = "ready" if running and permitted and accepted else "partial"
        error = self._errors.get(name)
        if not installed:
            error = "members_unavailable"
        elif requested and not permitted:
            error = (
                "baseline_executor_unavailable"
                if baseline_safety is not None
                else "operator_motion_permission_required"
            )
        elif requested and not accepted:
            error = "producer_acceptance_unavailable"
        return {
            "name": name,
            "scenario": feature.scenario,
            "title": feature.title,
            "description": feature.description,
            "title_en": feature.title_en,
            "description_en": feature.description_en,
            "ensure_cam": feature.ensure_cam,
            "tracking_mode": feature.tracking_mode,
            "aliases": sorted(alias for alias, target in self.aliases.items() if target == name),
            "host": "pi",
            "source": "pi",
            "observed_at": time.time(),
            "stale": any(row.get("stale") for row in services),
            "requested": requested,
            "state": state,
            "status": state,
            "active": requested and state == "ready",
            "ready": requested and running and permitted and accepted and state == "ready",
            "running": running,
            "installed": installed,
            "can_move": feature.can_move,
            "control_owner": feature.control_owner,
            "motion_owner": feature.control_owner,
            "control_generation": self._intents.get(name, {}).get("generation"),
            "request_id": self._intents.get(name, {}).get("request_id"),
            "options": options,
            "option_kind": feature.option_kind,
            "option_schema": option_schema(feature),
            "members": list(units),
            "required_actuators": ["move", "turn"] if feature.can_move else [],
            "actions": ["start", "stop"],
            "resources": list(task_resources(feature, options)),
            "services": services,
            "error": error,
            "baseline_safety": baseline_safety,
            "producer_statuses": producers,
            "missing_runtime_dependencies": self._dependency_errors.get(name, []),
        }

    def describe_features(self) -> list[dict]:
        # GET can show the transition while a slow systemd action owns the
        # mutation lock. Return the recorded age, not an invented fresh status.
        if not self._lock.acquire(blocking=False):
            return json.loads(json.dumps(self._snapshot_rows))
        try:
            rows = [self._describe(name) for name in self.registry]
            self._snapshot_rows = rows
            return rows
        finally:
            self._lock.release()

    def catalog(self) -> dict:
        return {
            **catalog_payload(),
            "observed_at": time.time(),
            "features": self.describe_features(),
            "resource_consumers": self.resource_consumers(),
        }

    def state_snapshot(self) -> dict:
        if not self._lock.acquire(blocking=False):
            return json.loads(json.dumps(self._last_snapshot))
        try:
            rows = self.describe_features()
            self._last_snapshot = {
                "contract_version": CONTRACT_VERSION,
                "host": "pi",
                "source": "pi",
                "observed_at": time.time(),
                "ts": time.time(),
                "active": [row["name"] for row in rows if row["active"]],
                "requested": sorted(self._requested),
                "features": rows,
                "resource_consumers": self.resource_consumers(),
                "service_intents": self._service_intents(),
                "service_domains": dict(self._service_domains),
            }
            return json.loads(json.dumps(self._last_snapshot))
        finally:
            self._lock.release()

    def _service_intents(self) -> dict:
        intents = dict(self._admin_intents)
        for name, intent in self._intents.items():
            feature = self.registry[name]
            options = self._requested.get(name, self._pending.get(name, {}))
            for unit in task_units(feature, options):
                meta = UNIT_CATALOG.get(unit, {})
                if meta.get("can_move") and meta.get("motion_owner") == feature.control_owner:
                    intents[unit] = {**intent, "task": name}
        return intents

    def _persist_state(self) -> bool:
        data = self.state_snapshot()
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self._state_path)
            return True
        except OSError:
            # A movement producer must bind the accepted generation before start.
            return False
