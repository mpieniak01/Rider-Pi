"""One bounded operator request prepares a Pi-owned navigation trial.

No actuator is accessed here: every ARM/STOP uses the existing motion executor,
and every service change uses the shared FeatureManager transaction.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from pathlib import Path

from apps.motion import manual_settings
from apps.safety.state import atomic_write
from common.service_catalog import CAMERA_CAPTURE_UNITS, task_units
from services import navigation_config
from services.control_commands import submit_control
from services.safety_contract import read_status

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


def validate_request(body, now):
    if not isinstance(body, dict) or set(body) != FIELDS:
        raise TrialError("navigation_trial_invalid", 400)
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


def public_status(row, *, sampled_now=None, fresh=True):
    """Convert Pi-local samples to durations; never export a monotonic epoch."""
    result = dict(row)
    sampled = result.pop("sampled_monotonic", None)
    result.pop("run_started_monotonic", None)
    elapsed_ms = None
    sampled_now = time.monotonic() if sampled_now is None else sampled_now
    if fresh and type(sampled) in (int, float) and math.isfinite(sampled):
        delta = sampled_now - sampled
        if math.isfinite(delta) and delta >= 0:
            elapsed_ms = delta * 1000
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
        body = validate_request(payload, self.wall())
        context = {
            "generation": body["generation"],
            "owner": None,
            "state": None,
            "revision": body["config_revision"],
            "settings_revision": body["settings_revision"],
            "deadline": self.clock() + 5.0,
            "armed": False,
            "sequence": None,
            "phase": "acquiring_lock",
            "producer_not_before": None,
            "started": self.clock(),
            "phase_started": self.clock(),
            "phase_timings_ms": {},
        }
        local_id = "trial-" + hashlib.sha256(body["request_id"].encode()).hexdigest()[:32]
        start_id = local_id + "-start"

        progress_path = self.manager._state_path.with_name("navigation_trial_prepare.json")

        def progress(phase, state="preparing", error=None):
            now = self.clock()
            previous = context["phase"]
            elapsed = (now - context["phase_started"]) * 1000
            timings = dict(context["phase_timings_ms"])
            timings[previous] = round(timings.get(previous, 0.0) + elapsed, 2)
            context.update(phase=phase, phase_started=now, phase_timings_ms=timings)
            row = {
                "request_id": body["request_id"],
                "phase": phase,
                "state": state,
                "elapsed_ms": round((now - context["started"]) * 1000, 2),
                "phase_timings_ms": timings,
                "observed_at": self.wall(),
                "error": error,
            }
            try:
                atomic_write(progress_path, row)
            except OSError:
                # Progress is diagnostic; admission and motion journals are separate.
                pass
            return row

        def matching_run():
            if context["producer_not_before"] is None:
                return None
            row = self.status()
            observed = row.get("observed_at")
            if (
                row.get("mode") == "drive"
                and row.get("config_revision") == context["revision"]
                and row.get("generation") == context.get("arm_generation")
                and row.get("operator_request_id") == start_id
                and isinstance(row.get("run_id"), str)
                and row["run_id"]
                and type(observed) in (int, float)
                and math.isfinite(observed)
                and context["producer_not_before"] <= observed <= self.wall() + 0.1
            ):
                return row
            return None

        def started_in_budget(row):
            if not row or row.get("running") is not True or row.get("latched") is True:
                return False
            birth = row.get("run_started_monotonic")
            sampled = row.get("sampled_monotonic")
            return (
                type(birth) in (int, float)
                and math.isfinite(birth)
                and context["started"] <= birth < context["deadline"]
                and type(sampled) in (int, float)
                and math.isfinite(sampled)
                and 0 <= self.clock() - sampled <= 1.0
            )

        def guard():
            if self.clock() >= context["deadline"] and not (
                context["phase"] in {"start_navigation", "first_status"} and started_in_budget(matching_run())
            ):
                raise TrialError(
                    "navigation_trial_prepare_timeout",
                    504,
                    details={"preparation": progress(context["phase"], "failed", "navigation_trial_prepare_timeout")},
                )
            safety = self.safety()
            if (
                safety.get("generation") != context["generation"]
                or safety.get("owner") != context["owner"]
                or safety.get("state") != context["state"]
                or safety.get("stale") is True
                or safety.get("ready") is not True
                or context["sequence"] is not None
                and safety.get("last_seq") != context["sequence"]
            ):
                raise TrialError("navigation_trial_cancelled")
            if (
                self.settings().get("revision") != context["settings_revision"]
                or (safety.get("manual_settings") or {}).get("revision") != context["settings_revision"]
            ):
                raise TrialError("manual_settings_stale")
            if self.policy().get("revision") != context["revision"]:
                raise TrialError("navigation_configuration_conflict")
            return safety

        def stop_old(owner):
            safety = self.safety()
            if safety.get("generation") != context["generation"]:
                # Only a fresh executor generation confirms revocation. Missing
                # telemetry cannot be mistaken for a successful scoped STOP.
                if (
                    isinstance(safety.get("generation"), str)
                    and safety["generation"]
                    and safety.get("state") in {"ARMED", "DISARMED", "ESTOP"}
                    and safety.get("stale") is not True
                ):
                    return {"ok": True, "confirmed": True, "superseded": True, "permission_revoked": True}
                return {"ok": False, "confirmed": False, "error": "navigation_trial_authority_unknown"}
            result, code = self.submit(
                {
                    "action": "stop",
                    "source": owner or "manual",
                    "request_id": local_id + "-stop",
                    "expected_generation": context["generation"],
                }
            )
            if code != 200 or not result.get("ok") or not result.get("confirmed"):
                return {**result, "ok": False}
            # Only this STOP's matching ACK may advance our expected generation.
            ack = result.get("ack") or {}
            next_generation = ack.get("generation")
            current = self.safety()
            if (
                not isinstance(next_generation, str)
                or not next_generation
                or current.get("generation") != next_generation
                or current.get("state") != "DISARMED"
                or current.get("owner") is not None
            ):
                raise TrialError("navigation_trial_cancelled")
            context.update(generation=next_generation, owner=None, state="DISARMED", sequence=current.get("last_seq"))
            return result

        with self.manager.operation(
            guard=guard,
            remaining=lambda: max(0.0, context["deadline"] - self.clock()),
            stop=stop_old,
            observation_units=tuple(
                set(CAMERA_CAPTURE_UNITS).union(
                    *(
                        task_units(self.manager.registry[name], {})
                        for name in ("s2_camera_preview", "s14_venom_navigation", "s15_venom_perception")
                    )
                )
            ),
        ):
            try:
                # Freshness is checked again after acquiring task serialization.
                validate_request(body, self.wall())
                progress("admission")
                safety = self.safety()
                if (
                    safety.get("generation") != body["generation"]
                    or safety.get("ready") is not True
                    or safety.get("stale") is True
                    or safety.get("state") not in {"ARMED", "DISARMED"}
                ):
                    raise TrialError("navigation_trial_authority_changed")
                if (
                    safety.get("remote_decision_deadline_supported") is not True
                    or safety.get("scoped_stop_generation_supported") is not True
                ):
                    raise TrialError("navigation_executor_update_required")
                context.update(owner=safety.get("owner"), state=safety["state"], sequence=safety.get("last_seq"))
                guard()
                policy = self.policy()
                if not policy.get("verified") or not policy.get("calibration_id") or not policy.get("model_sha256"):
                    raise TrialError("navigation_validation_required")
                self._reserve(body)
                # Reserve the passive consumer before releasing the old producer.
                # Otherwise S15's last-owner cleanup stops the shared camera/feed.
                progress("camera_reservation")
                guard()
                result = self.manager.set_feature("s2_camera_preview", True)
                guard()
                self._accepted(result)
                progress("stop_old_producer")
                for name in ("s14_venom_navigation", "s15_venom_perception"):
                    guard()
                    result = self.manager.set_feature(name, False)
                    guard()
                    self._accepted(result)
                progress("configure")
                guard()
                config = self.configure({"revision": context["revision"], "values": {"mode": "drive"}})
                context["revision"] = config["revision"]
                progress("authority_handoff")
                safety = guard()
                if safety["state"] == "ARMED":
                    self._accepted(stop_old(safety.get("owner")))
                safety = guard()
                progress("arm_ack")
                context["armed"] = True
                context["arm_generation"] = context["generation"]
                arm, code = self.submit(
                    {
                        "action": "arm",
                        "source": "manual",
                        "owner": "navigation",
                        "request_id": local_id + "-arm",
                        "generation": context["generation"],
                        "seq": self._next_sequence(safety),
                        "ts": self.wall(),
                        "ttl_ms": 500,
                        "operator_consent": True,
                        "operator_plan": body["operator_plan"],
                        "execution_context": "panel",
                        "arming_mode": "timed",
                        "lease_s": 10.0,
                    }
                )
                if code != 200 or not arm.get("ok") or not arm.get("confirmed"):
                    raise TrialError(arm.get("error") or "navigation_trial_arm_unconfirmed")
                context.update(owner="navigation", state="ARMED", sequence=None)
                safety = guard()
                if safety.get("can_move") is not True:
                    raise TrialError("operator_motion_permission_required")
                started = self.wall()
                context["producer_not_before"] = started
                control = {
                    "request_id": start_id,
                    "settings_revision": context["settings_revision"],
                    "source": "navigation",
                    "generation": context["generation"],
                    "seq": self._next_sequence(safety),
                    "ts": self.wall(),
                    "ttl_ms": 500,
                    "operator_consent": True,
                    "operator_plan": body["operator_plan"],
                    "execution_context": "panel",
                }
                progress("start_navigation")
                result = self.manager.set_feature("s14_venom_navigation", True, control=control)
                actual = matching_run()
                if actual and actual.get("running") is False:
                    raise TrialError(
                        "navigation_trial_stopped",
                        details={"started": True, "status": public_status(actual, fresh=False)},
                    )
                guard()
                self._accepted(result)
                progress("first_status")
                while True:
                    authority = guard()
                    row = self.status()
                    if (
                        row.get("mode") == "drive"
                        and row.get("config_revision") == config["revision"]
                        and row.get("generation") == context["generation"]
                        and row.get("operator_request_id") == start_id
                        and isinstance(row.get("run_id"), str)
                        and row["run_id"]
                        and type(row.get("observed_at")) in (int, float)
                        and math.isfinite(row["observed_at"])
                        and max(started, self.wall() - 1.0) <= row["observed_at"] <= self.wall() + 0.1
                    ):
                        if row.get("running") is not True:
                            raise TrialError(
                                "navigation_trial_stopped",
                                details={"status": public_status(row, sampled_now=self.clock())},
                            )
                        preparation = progress("ready", "completed")
                        return {
                            "ok": True,
                            "preparation": preparation,
                            "request_id": body["request_id"],
                            "config": config,
                            "status": public_status(row, sampled_now=self.clock()),
                            "authority": authority,
                        }
                    self.sleep(min(0.02, max(0.0, context["deadline"] - self.clock())))
            except Exception as caught:
                error = caught
                # A producer may already have run and stopped while systemd/start
                # bookkeeping was blocking. Its matching outcome is authoritative.
                if context["producer_not_before"] is not None:
                    try:
                        actual = matching_run()
                    except Exception:
                        actual = None
                    if actual and actual.get("running") is False:
                        error = TrialError(
                            "navigation_trial_stopped",
                            details={"started": True, "status": public_status(actual, fresh=False)},
                        )
                # Keep the passive reservation on failure, without restoring a
                # producer, ARM or drive after a newer operator STOP/takeover.
                diagnostic = progress(
                    context["phase"], "failed", getattr(error, "code", "navigation_trial_prepare_failed")
                )
                if context["armed"]:
                    # Each cleanup attempt is independent: a broken service
                    # backend must not skip cancellation of a queued ARM.
                    try:
                        self.manager.set_feature("s14_venom_navigation", False)
                    except Exception:
                        pass
                    try:
                        current = self.safety()
                        if current.get("generation") == context.get("arm_generation") and current.get("owner") in {
                            None,
                            "navigation",
                        }:
                            # Invalidate a delayed ARM too, even if its ACK has
                            # not arrived and the sampled executor is disarmed.
                            stop_old("navigation")
                    except Exception:
                        pass
                if isinstance(error, TrialError):
                    error.details = {**(error.details or {}), "preparation": diagnostic}
                    raise error from None
                known = {
                    "compute_stop_goals_first",
                    "navigation_stop_goals_first",
                    "navigation_configuration_conflict",
                    "navigation_validation_required",
                    "navigation_goal_state_unavailable",
                }
                if isinstance(error, ValueError) and str(error) in known:
                    raise TrialError(str(error)) from error
                # Library/backend exception text can contain private inputs.
                raise TrialError("navigation_trial_prepare_failed", 503, details={"preparation": diagnostic}) from error

    @staticmethod
    def _accepted(result):
        if not result.get("ok"):
            raise TrialError(result.get("error") or "navigation_trial_prepare_failed", 503)

    @staticmethod
    def _next_sequence(safety):
        previous = safety.get("last_seq")
        return previous + 1 if type(previous) is int and previous >= -1 else 0
