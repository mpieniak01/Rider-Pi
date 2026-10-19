"""Observed task state, moved from the orchestrator without changing imports."""

from __future__ import annotations

import json
import time

from apps.voice.domain_profiles import expand
from common.secure_files import atomic_write
from common.service_catalog import (
    CONTRACT_VERSION,
    UNIT_CATALOG,
    catalog_payload,
    option_schema,
    task_availability,
    task_domain,
    task_resources,
    task_units,
    tracking_mode_for,
)

VENOM_NAVIGATION_UNIT = "rider-venom-navigation.service"
NAVIGATOR_UNIT = "rider-navigator.service"
VOICE_UNIT = "rider-voice-web.service"
MOVING_PRODUCERS = {"rider-tracking-controller.service", NAVIGATOR_UNIT, VENOM_NAVIGATION_UNIT}


class FeatureStateMixin:
    @staticmethod
    def _requires_producer(feature, units) -> bool:
        return bool(set(units) & MOVING_PRODUCERS or VOICE_UNIT in units)

    def _voice_producer_readiness(self, feature, options):
        status = self.producer_status(VOICE_UNIT)
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
        observed_unit = self._status(VOICE_UNIT)
        if "pid" in observed_unit:
            observed_pid = observed_unit["pid"]
            valid = valid and isinstance(observed_pid, int) and not isinstance(observed_pid, bool)
            valid = valid and observed_pid > 0 and status.get("pid") == observed_pid
        return status, valid

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
            if unit in {NAVIGATOR_UNIT, VENOM_NAVIGATION_UNIT}:
                valid = (
                    valid
                    and status.get("data_ready") is True
                    and status.get("navigation_ready") is True
                    and status.get("offline") is not True
                    and not status.get("error")
                    and not status.get("data_error")
                )
            observed_unit = self._status(unit)
            if "pid" in observed_unit:
                observed_pid = observed_unit["pid"]
                valid = valid and isinstance(observed_pid, int) and not isinstance(observed_pid, bool)
                valid = valid and observed_pid > 0 and status.get("pid") == observed_pid
            accepted = accepted and valid
            statuses.append({**status, "unit": unit, "matches_task": valid})
        if VOICE_UNIT in units:
            status, valid = self._voice_producer_readiness(feature, options)
            accepted = accepted and valid
            statuses.append({**status, "matches_task": valid})
        return accepted, statuses

    def _described_services(self, units):
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
        return services

    @staticmethod
    def _navigation_producer_error(navigation, intent):
        producer_error = navigation.get("data_error") or navigation.get("error")
        if (
            navigation.get("stale") is True
            or navigation.get("generation") != intent.get("generation")
            or navigation.get("request_id") != intent.get("request_id")
            or not intent.get("request_id")
            or not isinstance(producer_error, str)
            or not producer_error
        ):
            producer_error = None
        else:
            producer_error = producer_error[:512]
        return producer_error

    def _described_state(self, name, requested, running, permitted, accepted, producer_error, producers):
        state = self._states.get(name, "stopped")
        if requested and state == "starting" and running and permitted and accepted:
            state = "ready"
        elif (
            requested
            and state == "starting"
            and (
                not permitted
                or producer_error is not None
                or time.monotonic() - self._started_at.get(name, time.monotonic()) >= 5
                or any(status.get("stale") is not True and status.get("missing") for status in producers)
            )
        ):
            state = "partial"
        elif requested and state not in {"starting", "stopping", "failed", "partial"}:
            state = "ready" if running and permitted and accepted else "partial"
        return state

    def _described_error(self, name, installed, requested, producer_error, permitted, baseline_safety, accepted):
        error = self._errors.get(name)
        if not installed:
            error = "members_unavailable"
        elif requested and producer_error:
            error = producer_error
        elif requested and not permitted:
            error = (
                "baseline_executor_unavailable"
                if baseline_safety is not None
                else "operator_motion_permission_required"
            )
        elif requested and not accepted:
            error = "producer_acceptance_unavailable"
        return error

    def _feature_permissions(self, feature, available, installed):
        allowed = available["start_available"] and installed and self._permission(feature) is None
        if not available["start_available"]:
            reason = available["start_unavailable_reason"]
        elif not installed:
            reason = "unit_unavailable"
        elif self._permission(feature) is None:
            reason = None
        else:
            reason = "operator_motion_permission_required"
        return {
            "start": {"allowed": allowed, "reason": reason},
            "stop": {"allowed": True, "reason": None},
        }

    def _described_permission(self, name, feature, requested):
        permitted = self._permission(feature) is None
        baseline_safety = self.safety_status() if name == "s0_core" else None
        if baseline_safety is not None:
            permitted = baseline_safety.get("ready") is True and baseline_safety.get("stale") is not True
        intent = self._intents.get(name, {})
        if feature.can_move and requested:
            permitted = permitted and intent.get("generation") == self.safety_status().get("generation")
        return permitted, baseline_safety, intent

    def _describe(self, name: str) -> dict:
        feature = self.registry[name]
        requested = name in self._requested or name in self._pending
        options = self._requested.get(name, self._pending.get(name, {}))
        units = task_units(feature, options)
        available = task_availability(feature, options)
        services = self._described_services(units)
        installed = all(row["installed"] for row in services)
        running = installed and all(row["active"] for row in services)
        permitted, baseline_safety, intent = self._described_permission(name, feature, requested)
        accepted, producers = self._producer_readiness(feature, units, options) if requested else (True, [])
        # An admitted warm S14 remains a perception consumer while its motor
        # authority is paused/expired. Readiness is not a new motion permission.
        if (
            name == "s14_venom_navigation"
            and requested
            and accepted
            and any(
                row.get("unit") == VENOM_NAVIGATION_UNIT
                and row.get("operator_control_version") == 1
                and row.get("matches_task") is True
                for row in producers
            )
        ):
            permitted = True
        navigation = next((row for row in producers if row.get("unit") == NAVIGATOR_UNIT), {})
        producer_error = self._navigation_producer_error(navigation, intent)
        state = self._described_state(name, requested, running, permitted, accepted, producer_error, producers)
        error = self._described_error(name, installed, requested, producer_error, permitted, baseline_safety, accepted)
        return {
            "name": name,
            "scenario": feature.scenario,
            "title": feature.title,
            "description": feature.description,
            "title_en": feature.title_en,
            "description_en": feature.description_en,
            "ensure_cam": feature.ensure_cam,
            "tracking_mode": tracking_mode_for(feature, options),
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
            "permissions": self._feature_permissions(feature, available, installed),
            **available,
            "planning_request_available": False if NAVIGATOR_UNIT in units else None,
            "resources": list(task_resources(feature, options)),
            "services": services,
            "error": error,
            "baseline_safety": baseline_safety,
            "producer_statuses": producers,
            "data_ready": navigation.get("data_ready") is True if navigation else None,
            "navigation_ready": navigation.get("navigation_ready") is True if navigation else None,
            "data_error": producer_error,
            "missing_runtime_dependencies": self._dependency_errors.get(name, []),
        }

    def describe_features(self) -> list[dict]:
        # GET can show the transition while a slow systemd action owns the
        # mutation lock. Return the recorded age, not an invented fresh status.
        if not self._lock.acquire(blocking=False):
            return json.loads(json.dumps(self._snapshot_rows))
        try:
            from services.core.goal_journal import restore

            restore(self)
            rows = [self._describe(name) for name in self.registry]
            self._snapshot_rows = rows
            return rows
        finally:
            self._lock.release()

    def catalog(self) -> dict:
        from services.core.camera_state import snapshot
        from services.core.lcd_state import backlight_status

        return {
            **catalog_payload(),
            "api_envelope_versions": [1],
            "api_media_type": "application/vnd.rider.api+json;version=1",
            "observed_at": time.time(),
            "features": self.describe_features(),
            "resource_consumers": self.resource_consumers(),
            "resource_states": {
                "camera": snapshot(consumers=self.resource_consumers().get("camera", []), status_fn=self._status),
                "lcd": backlight_status(),
            },
        }

    def _persistence_rows(self) -> list[dict]:
        if self._operation_guard is None:
            return self.describe_features()
        # Ownership/intent is a control journal, not a full UI refresh. Keep
        # unrelated observations at their original age; refresh requested goals
        # and goals just stopped. Voice domain consumers still see current rows.
        rows = {row["name"]: row for row in self._snapshot_rows}
        changed = set(self._requested) | set(self._pending)
        changed.update(name for name, row in rows.items() if row.get("requested"))
        for name in changed:
            rows[name] = self._describe(name)
        self._snapshot_rows = list(rows.values())
        return self._snapshot_rows

    def state_snapshot(self) -> dict:
        if not self._lock.acquire(blocking=False):
            return json.loads(json.dumps(self._last_snapshot))
        try:
            rows = self._persistence_rows()
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
        from services.core.goal_journal import journal

        data["ownership_journal"] = journal(self)
        try:
            payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
            atomic_write(self._state_path, lambda stream: stream.write(payload))
            return True
        except OSError:
            # A movement producer must bind the accepted generation before start.
            return False
