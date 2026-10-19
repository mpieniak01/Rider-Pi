"""One bounded operator request prepares a Pi-owned navigation trial.

No actuator is accessed here: every ARM/STOP uses the existing motion executor,
and every service change uses the shared FeatureManager transaction.
"""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

from apps.motion import manual_settings
from apps.safety.state import atomic_write
from common.service_catalog import CAMERA_CAPTURE_UNITS as CAMERA_CAPTURE_UNITS, task_units as task_units
from services import navigation_config
from services.control_commands import submit_control
from services.safety_contract import read_status

PREPARATION_BUDGET_S = 15.0
ARMED_START_BUDGET_S = 5.0

FIELDS = {
    "request_id",
    "generation",
    "ts",
    "ttl_ms",
    "config_revision",
    "settings_revision",
    "operator_consent",
    "operator_plan",
    "source",
    "execution_context",
}


class TrialError(ValueError):
    def __init__(self, code, status=409, details=None):
        super().__init__(code)
        self.code, self.status, self.details = code, status, details


def _validate_operator_control(body):
    if ("panel_id" in body or "operator_control_version" in body) and (
        body.get("operator_control_version") != 1
        or type(body.get("operator_control_version")) is not int
        or not isinstance(body.get("panel_id"), str)
        or not body["panel_id"].strip()
        or len(body["panel_id"]) > 128
    ):
        raise TrialError("operator_control_invalid", 400)


def validate_request(body, now):
    if not isinstance(body, dict) or set(body) - {"panel_id", "operator_control_version"} != FIELDS:
        raise TrialError("navigation_trial_invalid", 400)
    _validate_operator_control(body)
    for key in ("request_id", "generation"):
        if not isinstance(body[key], str) or not 1 <= len(body[key]) <= 128:
            raise TrialError("navigation_trial_invalid", 400)
    if (
        body["operator_consent"] is not True
        or body["source"] != "manual"
        or body["execution_context"] != "panel"
        or not isinstance(body["operator_plan"], str)
        or not 1 <= len(body["operator_plan"].strip()) <= 512
    ):
        raise TrialError("navigation_trial_consent_required", 400)
    if any(type(body[key]) is not int or body[key] < 0 for key in ("config_revision", "settings_revision")):
        raise TrialError("navigation_trial_invalid", 400)
    if (
        type(body["ts"]) not in (int, float)
        or not math.isfinite(body["ts"])
        or type(body["ttl_ms"]) is not int
        or not 1 <= body["ttl_ms"] <= 500
        or not -0.1 <= now - body["ts"] <= body["ttl_ms"] / 1000
    ):
        raise TrialError("stale_or_invalid_operator_intent")
    return dict(body)


def navigation_status():
    target = Path(os.getenv("RIDER_NAVIGATION_STATUS", "/run/rider-motion/navigation_loop.json"))
    try:
        if target.stat().st_size > 16384:
            return {}
        row = json.loads(target.read_text())
        return row if isinstance(row, dict) else {}
    except (OSError, ValueError):
        return {}


def preparation_status(path, *, now=None):
    """Shared operation progress, independent of the last producer status."""
    now = time.time() if now is None else now
    try:
        target = Path(path)
        if target.stat().st_size > 16384:
            return None
        row = json.loads(target.read_text())
        age = now - row["observed_at"]
        if not isinstance(row, dict) or not math.isfinite(age) or age < 0:
            return None
        return {**row, "fresh": age <= (6.0 if row.get("state") == "preparing" else 60.0)}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _sample_elapsed(sampled, sampled_now, fresh):
    elapsed_ms = None
    if fresh and type(sampled) in (int, float) and math.isfinite(sampled):
        delta = sampled_now - sampled
        if math.isfinite(delta) and delta >= 0:
            elapsed_ms = delta * 1000
    return elapsed_ms


def public_status(row, *, sampled_now=None, fresh=True):
    """Convert Pi-local samples to durations; never export a monotonic epoch."""
    result = dict(row)
    failure = result.get("motion_failure") or {}
    if (
        result.get("mode") == "drive"
        and result.get("running") is False
        and result.get("stop_reason") == "motion_submission_failed"
        and failure.get("reason") == "stale_generation"
        and failure.get("gate_reason") == "consent_expired"
    ):
        result.update(stop_reason="trial_completed", motion_failure=None)
    sampled = result.pop("sampled_monotonic", None)
    result.pop("run_started_monotonic", None)
    sampled_now = time.monotonic() if sampled_now is None else sampled_now
    elapsed_ms = _sample_elapsed(sampled, sampled_now, fresh)
    remaining = result.get("permit_remaining_ms")
    result["permit_remaining_ms"] = (
        max(0.0, round(remaining - elapsed_ms, 2))
        if elapsed_ms is not None and type(remaining) in (int, float) and math.isfinite(remaining)
        else 0.0
    )
    feedback = result.get("feedback_remaining_ms")
    result["feedback_remaining_ms"] = (
        max(0.0, round(feedback - elapsed_ms, 2))
        if elapsed_ms is not None and type(feedback) in (int, float) and math.isfinite(feedback)
        else 0.0
    )
    result["waiting_feedback"] = (
        result.get("mode") == "drive"
        and result.get("running") is True
        and result.get("latched") is not True
        and result["permit_remaining_ms"] == 0
        and result["feedback_remaining_ms"] > 0
    )
    if result["waiting_feedback"]:
        result["paused"] = True
        if isinstance(result.get("decision"), dict):
            result["decision"] = {**result["decision"], "action": "stop", "motion_reason": "awaiting_fresh_decision"}
    response_age = result.get("response_age_ms")
    result["decision_age_ms"] = (
        round(response_age + elapsed_ms, 2)
        if elapsed_ms is not None and type(response_age) in (int, float) and math.isfinite(response_age)
        else None
    )
    return result


class NavigationTrial:
    def __init__(
        self,
        manager,
        *,
        safety=read_status,
        submit=submit_control,
        settings=manual_settings.read,
        policy=navigation_config.snapshot,
        configure=navigation_config.configure_locked,
        status=navigation_status,
        clock=time.monotonic,
        wall=time.time,
        sleep=time.sleep,
    ):
        self.manager = manager
        self.safety, self.submit, self.settings = safety, submit, settings
        self.policy, self.configure, self.status = policy, configure, status
        self.clock, self.wall, self.sleep = clock, wall, sleep

    def _reserve(self, body):
        # Called under the manager's cross-process task transaction.
        path = self.manager._state_path.with_name("navigation_trial_requests.json")
        try:
            if path.exists():
                if path.stat().st_size > 32768:
                    raise ValueError("oversized")
                row = json.loads(path.read_text())
                seen = row["requests"]
                if not isinstance(seen, list) or any(not isinstance(item, str) for item in seen):
                    raise ValueError("invalid")
            else:
                seen = []
            if body["request_id"] in seen:
                raise TrialError("navigation_trial_replay")
            atomic_write(path, {"requests": [*seen[-63:], body["request_id"]]})
        except TrialError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise TrialError("navigation_trial_journal_unavailable", 503) from exc

    def start(self, payload):
        from services.navigation_trial_preparation import TrialPreparation

        body = validate_request(payload, self.wall())
        accepted_at = self.clock()
        arrival = self.safety()
        return TrialPreparation(self, body, arrival, accepted_at).run()

    @staticmethod
    def _accepted(result):
        if not result.get("ok"):
            raise TrialError(result.get("error") or "navigation_trial_prepare_failed", 503)

    @staticmethod
    def _next_sequence(safety):
        previous = safety.get("last_seq")
        return previous + 1 if type(previous) is int and previous >= -1 else 0
