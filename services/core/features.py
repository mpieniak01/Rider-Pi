#!/usr/bin/env python3
"""Serialized task orchestration; observation never recreates operator intent."""

from __future__ import annotations

import math
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from common import runtime_dependencies, runtime_lock, systemd_ctrl, task_runtime
from common.service_catalog import (
    CAMERA_CAPTURE_UNITS,
    CONTRACT_VERSION,
    DEFAULT_ALIASES,
    DEFAULT_REGISTRY,
    PROTECTED_UNITS,
    UNIT_CATALOG,
    FeatureDefinition,
    task_resources,
    task_units,
)
from services.core.feature_admin import FeatureAdminMixin
from services.core.feature_state import FeatureStateMixin


class NullPublisher:
    """Explicit in-memory transport, for isolated tests only."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    def publish(self, topic: str, payload: dict, add_ts: bool = False) -> None:
        self.sent.append((topic, dict(payload)))


def _as_dict(result: object) -> dict:
    if hasattr(result, "as_dict"):
        return result.as_dict()
    if isinstance(result, dict):
        return result
    raise TypeError(f"Unsupported result type: {type(result)!r}")


def _safety_status() -> dict:
    try:
        from services.safety_contract import read_status

        return read_status()
    except (ImportError, OSError, ValueError) as exc:
        return {"ready": False, "can_move": False, "state": "UNKNOWN", "error": str(exc)}


def _safety_stop(owner: str | None) -> dict:
    try:
        from services.safety_contract import request_stop

        return request_stop(owner=owner)
    except (ImportError, OSError, ValueError) as exc:
        return {"ok": False, "confirmed": False, "error": str(exc)}


class FeatureManager(FeatureStateMixin, FeatureAdminMixin):
    """Reference-count shared units; only stop processes started by this manager.

    Existing processes belong to the external/base consumer. A restart observes
    them but never reconstructs a movement request from a saved state file.
    """

    PREVIEW_UNIT = "camera-capture@raw.service"
    FRAME_FEED_UNIT = "frame-distributor.service"

    def __init__(
        self,
        registry: dict[str, FeatureDefinition] | None = None,
        runner: Callable[[str, str], object] | None = None,
        status_fn: Callable[[str], object] | None = None,
        publisher: object | None = None,
        aliases: dict[str, str] | None = None,
        state_path: str | os.PathLike[str] | None = None,
        safety_status: Callable[[], dict] | None = None,
        safety_stop: Callable[[str | None], dict] | None = None,
        dependency_check: Callable[[tuple[str, ...], dict], list[str]] | None = None,
        producer_status: Callable[[str], dict] | None = None,
    ) -> None:
        self.registry = registry if registry is not None else DEFAULT_REGISTRY
        self.runner = runner or systemd_ctrl.run_unit_action
        self.status_fn = status_fn
        self.publisher = publisher  # lazy: GET/import must never open production BUS
        self.aliases = DEFAULT_ALIASES if aliases is None else aliases
        self.safety_status = safety_status or _safety_status
        self.safety_stop = safety_stop or _safety_stop
        self.dependency_check = dependency_check or runtime_dependencies.missing
        self.producer_status = producer_status or (
            lambda unit: task_runtime.read_status(unit, root=self._state_path.parent)
        )
        self._lock = threading.RLock()
        self._transaction_depth = 0
        self._requested: dict[str, dict] = {"s0_core": {}} if "s0_core" in self.registry else {}
        self._states: dict[str, str] = {}
        self._pending: dict[str, dict] = {}
        self._snapshot_rows: list[dict] = []
        self._snapshot_resource_consumers: dict[str, list[str]] = {}
        self._snapshot_unit_consumers: dict[str, list[str]] = {}
        self._last_snapshot: dict = {}
        self._intents: dict[str, dict] = {}
        self._admin_intents: dict[str, dict] = {}
        self._service_domains: dict[str, str] = {}
        self._dependency_errors: dict[str, list[str]] = {}
        self._started_at: dict[str, float] = {}
        self._intent_sequences: dict[tuple[str, str], int] = {}
        self._errors: dict[str, str] = {}
        self._managed_units: set[str] = set()
        self._admin_units: set[str] = set()
        self._state_path = Path(state_path or os.getenv("FEATURE_STATE_PATH", "/run/rider-motion/feature_state.json"))

    def _resolve_name(self, requested: str) -> str:
        canonical = requested if requested in self.registry else self.aliases.get(requested)
        if canonical in self.registry:
            return canonical
        raise ValueError(f"unknown feature: {requested}")

    def _status(self, unit: str) -> dict:
        value = self.status_fn(unit) if self.status_fn else systemd_ctrl.status(unit)
        if isinstance(value, bool):
            return {
                "unit": unit,
                "installed": True,
                "load": "loaded",
                "active": "active" if value else "inactive",
                "sub": "running" if value else "dead",
                "enabled": "disabled",
                "source": "fixture",
            }
        return dict(value)

    def _running(self, unit: str) -> bool:
        row = self._status(unit)
        return row.get("active") == "active" and row.get("load", "loaded") == "loaded" and not row.get("error")

    def _consumers(self, *, exclude: str | None = None) -> dict[str, list[str]]:
        consumers: dict[str, list[str]] = {}
        for name, options in self._requested.items():
            if name == exclude:
                continue
            for unit in task_units(self.registry[name], options):
                consumers.setdefault(unit, []).append(name)
        for unit in self._admin_units:
            consumers.setdefault(unit, []).append(f"admin:{unit}")
        return consumers

    def resource_consumers(self) -> dict[str, list[str]]:
        if not self._lock.acquire(blocking=False):
            return {resource: list(names) for resource, names in self._snapshot_resource_consumers.items()}
        try:
            consumers: dict[str, list[str]] = {}
            for name, options in {**self._requested, **self._pending}.items():
                for resource in task_resources(self.registry[name], options):
                    consumers.setdefault(resource, []).append(name)
            for unit in self._admin_units:
                for resource in UNIT_CATALOG[unit]["resources"]:
                    consumers.setdefault(resource, []).append(f"admin:{unit}")
                if unit == "rider-voice-web.service":
                    domain = self._service_domains.get(unit)
                    for resource in (
                        ()
                        if domain == "text"
                        else ("mic",)
                        if domain == "asr"
                        else ("speaker",)
                        if domain == "tts"
                        else ("mic", "speaker")
                    ):
                        consumers.setdefault(resource, []).append(f"admin:{unit}")
            self._snapshot_resource_consumers = consumers
            return {resource: list(names) for resource, names in consumers.items()}
        finally:
            self._lock.release()

    def unit_consumers(self, unit: str) -> list[str]:
        if not self._lock.acquire(blocking=False):
            return list(self._snapshot_unit_consumers.get(unit, []))
        try:
            consumers = self._consumers().get(unit, [])
            for name, options in self._pending.items():
                if unit in task_units(self.registry[name], options):
                    consumers = [*consumers, name]
            if unit in PROTECTED_UNITS:
                consumers = [*consumers, "base"]
            elif self._running(unit) and unit not in self._managed_units:
                consumers = [*consumers, "external"]
            self._snapshot_unit_consumers[unit] = sorted(set(consumers))
            return list(self._snapshot_unit_consumers[unit])
        finally:
            self._lock.release()

    @contextmanager
    def transaction(self):
        """Task and recovery changes serialize across API and maintenance CLI."""
        with self._lock:
            if self._transaction_depth:
                yield
            else:
                with runtime_lock.exclusive(self._state_path.with_suffix(".lock")):
                    self._transaction_depth += 1
                    try:
                        yield
                    finally:
                        self._transaction_depth -= 1

    def _run(self, unit: str, action: str) -> dict:
        try:
            result = _as_dict(self.runner(unit, action))
        except Exception as exc:
            result = {"ok": False, "unit": unit, "action": action, "error": str(exc)}
        systemd_ctrl.invalidate_snapshot()
        return result

    def _publish_tracking_mode(self, mode: str) -> None:
        if self.publisher is None:
            from common import bus

            self.publisher = bus.BusPub()
        self.publisher.publish("tracking.mode:set", {"mode": mode}, add_ts=True)

    def _permission(self, feature: FeatureDefinition) -> dict | None:
        if not feature.can_move:
            return None
        safety = self.safety_status()
        if (
            safety.get("ready") is not True
            or safety.get("can_move") is not True
            or safety.get("owner") != feature.control_owner
        ):
            return {"ok": False, "error": "operator_motion_permission_required", "safety": safety}
        capabilities = safety.get("capabilities", {})
        if not isinstance(capabilities, dict):
            capabilities = {}
        for action in ("move", "turn"):
            capability = capabilities.get(action, {})
            if (
                not isinstance(capability, dict)
                or capability.get("available") is not True
                or capability.get("stop_verified") is not True
            ):
                return {"ok": False, "error": "actuator_capability_unavailable", "action": action, "safety": safety}
        return None

    def _intent_permission(self, control: dict | None, *, consume: bool = True) -> dict | None:
        """The originally received intent cannot inherit a newer operator ARM."""
        control = control or {}
        safety = self.safety_status()
        source, generation = control.get("source"), control.get("generation")
        seq, ts, ttl = control.get("seq"), control.get("ts"), control.get("ttl_ms")
        valid_numbers = (
            not isinstance(seq, bool)
            and isinstance(seq, int)
            and seq >= 0
            and not isinstance(ts, bool)
            and isinstance(ts, (int, float))
            and math.isfinite(ts)
            and not isinstance(ttl, bool)
            and isinstance(ttl, (int, float))
            and math.isfinite(ttl)
            and 1 <= ttl <= 500
            and -0.1 <= time.time() - ts <= ttl / 1000
        )
        if (
            not valid_numbers
            or source not in {"manual", "follow_me", "navigation"}
            or not isinstance(generation, str)
            or not generation
            or generation != safety.get("generation")
            or not isinstance(control.get("request_id"), str)
            or not control["request_id"]
        ):
            return {"ok": False, "error": "stale_or_invalid_operator_intent", "safety": safety}
        key = (generation, source)
        if consume:
            if seq <= self._intent_sequences.get(key, -1):
                return {"ok": False, "error": "operator_intent_replay"}
            self._intent_sequences[key] = seq
            # Only current generations matter; bound memory independently of uptime.
            self._intent_sequences = {
                pair: value for pair, value in self._intent_sequences.items() if pair[0] == generation
            }
        return None

    def _conflicts(self, canonical: str, units: tuple[str, ...]) -> list[str]:
        requested_capture = set(units) & CAMERA_CAPTURE_UNITS
        feature = self.registry[canonical]
        conflicts: list[str] = []
        for name, options in self._requested.items():
            if name == canonical:
                continue
            other = self.registry[name]
            captures = set(task_units(other, options)) & CAMERA_CAPTURE_UNITS
            if (
                (requested_capture and captures and requested_capture != captures)
                or (feature.can_move and other.can_move)
                or (feature.tracking_mode and other.tracking_mode and feature.tracking_mode != other.tracking_mode)
            ):
                conflicts.append(name)
        # A raw/edge/ssd owner outside this task must not be stopped automatically.
        for unit in CAMERA_CAPTURE_UNITS - requested_capture:
            if requested_capture and self._running(unit):
                conflicts.append(unit)
        return sorted(set(conflicts))

    def _rollback(self, feature: FeatureDefinition, started: list[str]) -> list[dict]:
        results: list[dict] = []
        if feature.can_move and started:
            stop = self.safety_stop(feature.control_owner)
            results.append({"action": "revoke_control", **stop})
            if not stop.get("ok") or not stop.get("confirmed"):
                return results
        for unit in reversed(started):
            if unit in PROTECTED_UNITS or self._consumers().get(unit):
                continue
            result = self._run(unit, "stop")
            results.append(result)
            if result.get("ok"):
                self._managed_units.discard(unit)
        return results

    def _start(self, canonical: str, options: dict, control: dict | None = None) -> dict:
        feature = self.registry[canonical]
        units = task_units(feature, options)
        denied = self._permission(feature)
        if denied:
            return denied
        if feature.can_move:
            denied = self._intent_permission(control)
            if denied:
                return denied
        conflicts = self._conflicts(canonical, units)
        if conflicts:
            return {"ok": False, "error": "resource_conflict", "consumers": conflicts}
        if canonical in self._requested:
            if (
                self._requested[canonical] != options
                or feature.can_move
                and self._intents.get(canonical, {}).get("generation") != control.get("generation")
            ):
                return {"ok": False, "error": "stop_before_reconfigure"}
            row = self._describe(canonical)
            return {
                "ok": row["state"] == "ready",
                "idempotent": True,
                "task": row,
                "steps": [],
                "events": [],
                "error": row["error"],
            }
        missing = [unit for unit in units if self._status(unit).get("load", "loaded") != "loaded"]
        uncertain = [unit for unit in units if self._status(unit).get("error")]
        if missing or uncertain:
            self._states[canonical] = "failed"
            self._errors[canonical] = "members_unavailable"
            return {"ok": False, "error": "members_unavailable", "missing": missing, "unknown": uncertain}
        dependencies = self.dependency_check(units, options)
        self._dependency_errors[canonical] = dependencies
        if dependencies:
            self._states[canonical] = "failed"
            self._errors[canonical] = "runtime_dependencies_missing"
            return {"ok": False, "error": "runtime_dependencies_missing", "missing": dependencies}
        self._states[canonical] = "starting"
        self._started_at[canonical] = time.monotonic()
        self._pending[canonical] = dict(options)
        if feature.can_move:
            self._intents[canonical] = dict(control)
        self._snapshot_rows = self.describe_features()
        persisted = self._persist_state()
        if (feature.can_move or "rider-voice-web.service" in units) and not persisted:
            self._states[canonical] = "failed"
            self._errors[canonical] = "control_journal_unavailable"
            return {"ok": False, "error": "control_journal_unavailable"}
        started: list[str] = []
        steps: list[dict] = []
        events: list[dict] = []
        for unit in units:
            if feature.can_move and UNIT_CATALOG.get(unit, {}).get("can_move"):
                denied = self._permission(feature)
                if self.safety_status().get("generation") != control.get("generation"):
                    denied = {"ok": False, "error": "operator_generation_changed"}
                if denied:
                    rollback = self._rollback(feature, started)
                    self._states[canonical] = "partial" if any(not row.get("ok") for row in rollback) else "failed"
                    self._errors[canonical] = denied["error"]
                    if self._states[canonical] == "partial":
                        self._requested[canonical] = dict(options)
                    return {**denied, "steps": steps, "rollback": rollback, "state": self._states[canonical]}
            if self._running(unit):
                continue
            result = self._run(unit, "start")
            steps.append(result)
            if not result.get("ok") or not self._running(unit):
                if result.get("ok") or self._running(unit):
                    started.append(unit)
                    self._managed_units.add(unit)
                rollback = self._rollback(feature, started)
                partial = any(not item.get("ok") for item in rollback)
                self._states[canonical] = "partial" if partial else "failed"
                self._errors[canonical] = "start_failed"
                if partial:
                    self._requested[canonical] = dict(options)
                return {
                    "ok": False,
                    "error": "start_failed",
                    "steps": steps,
                    "rollback": rollback,
                    "state": self._states[canonical],
                    "events": events,
                }
            started.append(unit)
            self._managed_units.add(unit)
        denied = self._permission(feature)
        # Freshness was checked upon acceptance; startup can exceed its TTL.
        # The generation itself must still be exactly the accepted one.
        if feature.can_move and self.safety_status().get("generation") != control.get("generation"):
            denied = {"ok": False, "error": "operator_generation_changed"}
        if denied:
            rollback = self._rollback(feature, started)
            self._states[canonical] = "partial" if any(not row.get("ok") for row in rollback) else "failed"
            if self._states[canonical] == "partial":
                self._requested[canonical] = dict(options)
            self._errors[canonical] = denied["error"]
            return {**denied, "steps": steps, "rollback": rollback, "state": self._states[canonical]}
        if feature.tracking_mode:
            try:
                self._publish_tracking_mode(feature.tracking_mode)
                events.append({"topic": "tracking.mode:set", "mode": feature.tracking_mode})
            except Exception as exc:
                rollback = self._rollback(feature, started)
                self._states[canonical] = "partial" if any(not row.get("ok") for row in rollback) else "failed"
                self._errors[canonical] = str(exc)
                if self._states[canonical] == "partial":
                    self._requested[canonical] = dict(options)
                return {"ok": False, "error": "tracking_mode_failed", "steps": steps, "rollback": rollback}
        self._requested[canonical] = dict(options)
        self._states[canonical] = "starting" if self._requires_producer(feature, units) else "ready"
        self._errors.pop(canonical, None)
        return {"ok": True, "steps": steps, "events": events, "task": self._describe(canonical)}

    def _stop(self, canonical: str) -> dict:
        if canonical not in self._requested:
            return {"ok": True, "idempotent": True, "steps": [], "events": []}
        feature = self.registry[canonical]
        options = self._requested[canonical]
        self._states[canonical] = "stopping"
        self._snapshot_rows = self.describe_features()
        self._persist_state()
        steps: list[dict] = []
        if feature.can_move:
            revoked = self.safety_stop(feature.control_owner)
            steps.append({"action": "revoke_control", **revoked})
            if not revoked.get("ok") or not revoked.get("confirmed"):
                self._states[canonical] = "partial"
                self._errors[canonical] = "stop_unconfirmed"
                return {"ok": False, "error": "stop_unconfirmed", "steps": steps}
        remaining = self._consumers(exclude=canonical)
        failed: list[str] = []
        for unit in reversed(task_units(feature, options)):
            if unit in PROTECTED_UNITS or remaining.get(unit) or unit not in self._managed_units:
                continue
            result = self._run(unit, "stop")
            steps.append(result)
            if result.get("ok") and not self._running(unit):
                self._managed_units.discard(unit)
            else:
                failed.append(unit)
        if failed:
            self._states[canonical] = "partial"
            self._errors[canonical] = "stop_failed"
            return {"ok": False, "error": "stop_failed", "failed": failed, "steps": steps}
        self._requested.pop(canonical, None)
        self._intents.pop(canonical, None)
        self._states[canonical] = "stopped"
        self._errors.pop(canonical, None)
        events = []
        if feature.tracking_mode:
            try:
                self._publish_tracking_mode("none")
                events.append({"topic": "tracking.mode:set", "mode": "none"})
            except Exception as exc:
                return {"ok": False, "error": "tracking_mode_failed", "steps": steps, "detail": str(exc)}
        return {"ok": True, "steps": steps, "events": events, "task": self._describe(canonical)}

    def set_feature(self, name: str, enabled: bool, options: dict | None = None, control: dict | None = None) -> dict:
        if not isinstance(enabled, bool) or (options is not None and not isinstance(options, dict)):
            raise ValueError("enabled must be boolean and options an object")
        try:
            with self.transaction():
                canonical = self._resolve_name(name)
                try:
                    result = self._start(canonical, options or {}, control) if enabled else self._stop(canonical)
                finally:
                    self._pending.pop(canonical, None)
                    if canonical not in self._requested:
                        self._intents.pop(canonical, None)
                self._persist_state()
                return {
                    "contract_version": CONTRACT_VERSION,
                    "feature": canonical,
                    "request_id": (control or {}).get("request_id"),
                    **result,
                }
        except OSError as exc:
            return {"ok": False, "error": "orchestration_lock_unavailable", "detail": str(exc)}


__all__ = ["FeatureDefinition", "FeatureManager", "DEFAULT_REGISTRY", "DEFAULT_ALIASES", "NullPublisher"]
