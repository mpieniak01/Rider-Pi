"""Bounded navigation preparation transaction, independent of HTTP request handling."""

import hashlib
import math

from apps.safety.state import atomic_write
from common.service_catalog import CAMERA_CAPTURE_UNITS, task_units
from services.navigation_trial import ARMED_START_BUDGET_S, PREPARATION_BUDGET_S, TrialError, public_status


class TrialPreparation:
    def __init__(self, trial, body, arrival, accepted_at):
        self.manager = trial.manager
        self.safety, self.submit, self.settings = trial.safety, trial.submit, trial.settings
        self.policy, self.configure, self.status = trial.policy, trial.configure, trial.status
        self.clock, self.wall, self.sleep = trial.clock, trial.wall, trial.sleep
        self._reserve, self._accepted, self._next_sequence = trial._reserve, trial._accepted, trial._next_sequence
        self.body, self.arrival = body, arrival
        self.context = {
            "generation": body["generation"],
            "owner": None,
            "state": None,
            "revision": body["config_revision"],
            "settings_revision": body["settings_revision"],
            "deadline": accepted_at + PREPARATION_BUDGET_S,
            "armed": False,
            "sequence": None,
            "phase": "acquiring_lock",
            "producer_not_before": None,
            "started": accepted_at,
            "phase_started": accepted_at,
            "phase_timings_ms": {},
        }
        self.is_journey = body.get("journey_version") == 1
        self.warm_reused = False
        prefix = "journey-" if self.is_journey else "trial-"
        self.local_id = prefix + hashlib.sha256(body["request_id"].encode()).hexdigest()[:32]
        self.start_id = self.local_id + "-start"

        self.progress_path = self.manager._state_path.with_name("navigation_trial_prepare.json")

    def progress(self, phase, state="preparing", error=None):
        now = self.clock()
        previous = self.context["phase"]
        elapsed = (now - self.context["phase_started"]) * 1000
        timings = dict(self.context["phase_timings_ms"])
        timings[previous] = round(timings.get(previous, 0.0) + elapsed, 2)
        self.context.update(phase=phase, phase_started=now, phase_timings_ms=timings)
        row = {
            "request_id": self.body["request_id"],
            **({"journey_version": 1} if self.is_journey else {}),
            "phase": phase,
            "state": state,
            "elapsed_ms": round((now - self.context["started"]) * 1000, 2),
            "phase_timings_ms": timings,
            "observed_at": self.wall(),
            "error": error,
            "warm_reused": self.warm_reused,
        }
        try:
            atomic_write(self.progress_path, row)
        except OSError:
            # Progress is diagnostic; admission and motion journals are separate.
            pass
        return row

    def matching_run(self):
        if self.context["producer_not_before"] is None:
            return None
        row = self.status()
        observed = row.get("observed_at")
        if (
            row.get("mode") == "drive"
            and row.get("config_revision") == self.context["revision"]
            and row.get("generation") == self.context.get("arm_generation")
            and row.get("operator_request_id") == self.start_id
            and isinstance(row.get("run_id"), str)
            and row["run_id"]
            and type(observed) in (int, float)
            and math.isfinite(observed)
            and self.context["producer_not_before"] <= observed <= self.wall() + 0.1
        ):
            return row
        return None

    def started_in_budget(self, row):
        if not row or row.get("running") is not True or row.get("latched") is True:
            return False
        birth = row.get("run_started_monotonic")
        sampled = row.get("sampled_monotonic")
        return (
            type(birth) in (int, float)
            and math.isfinite(birth)
            and self.context["started"] <= birth < self.context["deadline"]
            and type(sampled) in (int, float)
            and math.isfinite(sampled)
            and 0 <= self.clock() - sampled <= 1.0
        )

    def guard(self):
        safety = self.safety()
        if (
            safety.get("generation") != self.context["generation"]
            or safety.get("owner") != self.context["owner"]
            or safety.get("state") != self.context["state"]
            or safety.get("stale") is True
            or safety.get("ready") is not True
            or self.context["sequence"] is not None
            and safety.get("last_seq") != self.context["sequence"]
        ):
            raise TrialError("navigation_trial_cancelled")
        if (
            self.settings().get("revision") != self.context["settings_revision"]
            or (safety.get("manual_settings") or {}).get("revision") != self.context["settings_revision"]
        ):
            raise TrialError("manual_settings_stale")
        if self.policy().get("revision") != self.context["revision"]:
            raise TrialError("navigation_configuration_conflict")
        if self.clock() >= self.context["deadline"] and not (
            self.context["phase"] in {"start_navigation", "first_status"}
            and self.started_in_budget(self.matching_run())
        ):
            raise TrialError(
                "navigation_trial_prepare_timeout",
                504,
                details={
                    "preparation": self.progress(self.context["phase"], "failed", "navigation_trial_prepare_timeout")
                },
            )
        return safety

    def stop_old(self, owner):
        safety = self.safety()
        if safety.get("generation") != self.context["generation"]:
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
                "request_id": self.local_id + "-stop",
                "expected_generation": self.context["generation"],
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
        self.context.update(generation=next_generation, owner=None, state="DISARMED", sequence=current.get("last_seq"))
        return result

    def _admit(self):
        # Accepted at arrival. Serialization/restore must not age the
        # original click out of its ingress TTL. The original generation,
        # settings and bounded preparation are rechecked below.
        self.progress("admission")
        safety = self.safety()
        if (
            safety.get("generation") != self.body["generation"]
            or any(safety.get(key) != self.arrival.get(key) for key in ("generation", "owner", "state", "last_seq"))
            or self.arrival.get("ready") is not True
            or self.arrival.get("stale") is True
            or safety.get("ready") is not True
            or safety.get("stale") is True
            or safety.get("state") not in {"ARMED", "DISARMED"}
        ):
            raise TrialError("navigation_trial_authority_changed")
        if (
            safety.get("remote_decision_deadline_supported") is not True
            or safety.get("remote_decision_feedback_supported") is not True
            or safety.get("scoped_stop_generation_supported") is not True
        ):
            raise TrialError("navigation_executor_update_required")
        self.context.update(owner=safety.get("owner"), state=safety["state"], sequence=safety.get("last_seq"))
        self.guard()
        policy = self.policy()
        if not policy.get("verified") or not policy.get("calibration_id") or not policy.get("model_sha256"):
            raise TrialError("navigation_validation_required")
        if self.is_journey:
            avoidance = policy.get("avoidance") or {}
            if type(safety.get("navigation_journey_version")) is not int or safety["navigation_journey_version"] != 1:
                raise TrialError("navigation_journey_update_required")
            if (
                avoidance.get("enabled") is not True
                or avoidance.get("protocol_version") != 3
                or avoidance.get("sweep_verified") is not True
            ):
                raise TrialError("navigation_journey_avoidance_required")
            from services.navigation_config import validate

            try:
                validate({**policy, "mode": "drive"})
            except ValueError as exc:
                raise TrialError(str(exc)) from exc
        self._reserve(self.body)

    def _prepare_sources(self):
        # Reserve the passive consumer before releasing the old producer.
        # Otherwise S15's last-owner cleanup stops the shared camera/feed.
        self.progress("camera_reservation")
        self.guard()
        result = self.manager.set_feature("s2_camera_preview", True)
        self.guard()
        self._accepted(result)
        if self.is_journey and self._warm_source_ready():
            self.warm_reused = True
            self.progress("warm_producer_reuse")
            return self.policy()
        self.progress("stop_old_producer")
        for name in ("s14_venom_navigation", "s15_venom_perception"):
            self.guard()
            result = self.manager.set_feature(name, False)
            self.guard()
            self._accepted(result)
        self.progress("configure")
        self.guard()
        config = self.configure({"revision": self.context["revision"], "values": {"mode": "drive"}})
        self.context["revision"] = config["revision"]
        from apps.compute.stream_prepare import prepare_stream

        self.progress("stream_prepare")
        self.guard()
        prepare_stream(
            timeout_s=min(2.0, max(0.01, self.context["deadline"] - self.clock())),
            max_age_ms=config.get("decision_budget_ms", 300),
            **({"journey_version": 1} if self.is_journey else {}),
        )
        self.guard()
        return config

    def _warm_source_ready(self):
        row = self.status()
        sampled = row.get("sampled_monotonic")
        if not (
            row.get("warm_navigation_version") == 1
            and type(row.get("warm_navigation_version")) is int
            and row.get("warm_ready") is True
            and row.get("running") is True
            and row.get("mode") == "observe"
            and self.policy().get("mode") == "drive"
            and row.get("config_revision") == self.context["revision"]
            and type(sampled) in (int, float)
            and math.isfinite(sampled)
            and 0 <= self.clock() - sampled <= 1.0
            and isinstance(row.get("warm_source"), dict)
        ):
            return False
        from apps.compute.stream_prepare import prepare_stream

        self.progress("warm_source_check")
        from apps.compute.client import ComputeError

        try:
            prepared = prepare_stream(
                timeout_s=min(2.0, max(0.01, self.context["deadline"] - self.clock())),
                max_age_ms=self.policy().get("decision_budget_ms", 300),
                journey_version=1,
            )
        except ComputeError as exc:
            if exc.code not in {"navigation_stream_source_mismatch", "navigation_stream_prepare_timeout"}:
                raise
            # Only probe incompatibility is recoverable; the same authority and
            # total preparation deadline still guard any cold fallback.
            self.guard()
            return False
        self.guard()
        source = (prepared or {}).get("latest_source")
        keys = ("camera_session", "transport_epoch", "pipeline_revision")
        return isinstance(source, dict) and all(
            row["warm_source"].get(key) == source.get(key) and source.get(key) is not None for key in keys
        )

    def _arm_navigation(self):
        self.progress("authority_handoff")
        safety = self.guard()
        if safety["state"] == "ARMED":
            self._accepted(self.stop_old(safety.get("owner")))
        safety = self.guard()
        self.progress("arm_ack")
        # Service shutdown/camera preparation need no driving permission.
        # Once ARM is requested, keep the shorter final-start bound.
        self.context["deadline"] = min(self.context["deadline"], self.clock() + ARMED_START_BUDGET_S)
        self.context["armed"] = True
        self.context["arm_generation"] = self.context["generation"]
        arm, code = self.submit(
            {
                "action": "arm",
                "source": "manual",
                "owner": "navigation",
                "request_id": self.local_id + "-arm",
                "generation": self.context["generation"],
                "seq": self._next_sequence(safety),
                "ts": self.wall(),
                "ttl_ms": 500,
                "operator_consent": True,
                "operator_plan": self.body["operator_plan"],
                "execution_context": "panel",
                "arming_mode": "journey" if self.is_journey else "timed",
                **(
                    {
                        "journey_version": 1,
                        "journey_id": self.body["request_id"],
                        "operator_origin_generation": self.body["generation"],
                    }
                    if self.is_journey
                    else {"lease_s": 10.0}
                ),
                **(
                    {"panel_id": self.body["panel_id"], "operator_control_version": 1}
                    if self.body.get("operator_control_version") == 1
                    else {}
                ),
            }
        )
        if code != 200 or not arm.get("ok") or not arm.get("confirmed"):
            raise TrialError(arm.get("error") or "navigation_trial_arm_unconfirmed")
        self.context.update(owner="navigation", state="ARMED", sequence=None)
        safety = self.guard()
        if safety.get("can_move") is not True:
            raise TrialError("operator_motion_permission_required")
        return safety

    def _start_producer(self, safety):
        started = self.wall()
        self.context["producer_not_before"] = started
        control = {
            "request_id": self.start_id,
            "settings_revision": self.context["settings_revision"],
            "source": "navigation",
            "generation": self.context["generation"],
            "seq": self._next_sequence(safety),
            "ts": self.wall(),
            "ttl_ms": 500,
            "operator_consent": True,
            "operator_plan": self.body["operator_plan"],
            "execution_context": "panel",
            **({"warm_navigation_version": 1} if self.warm_reused else {}),
        }
        self.progress("start_navigation")
        result = self.manager.set_feature("s14_venom_navigation", True, control=control)
        self.guard()
        actual = self.matching_run()
        if actual and actual.get("running") is False:
            raise TrialError(
                "navigation_trial_stopped",
                details={"started": True, "status": public_status(actual, fresh=False)},
            )
        self.guard()
        self._accepted(result)
        return started

    def _await_status(self, config, started):
        self.progress("first_status")
        while True:
            authority = self.guard()
            row = self.status()
            if (
                row.get("mode") == "drive"
                and row.get("config_revision") == config["revision"]
                and row.get("generation") == self.context["generation"]
                and row.get("operator_request_id") == self.start_id
                and (
                    not self.is_journey
                    or (row.get("journey") or {}).get("id") == self.body["request_id"]
                    and (row.get("journey") or {}).get("active") is True
                    and type((row.get("journey") or {}).get("version")) is int
                    and row["journey"]["version"] == 1
                )
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
                preparation = self.progress("ready", "completed")
                return {
                    "ok": True,
                    "preparation": preparation,
                    "request_id": self.body["request_id"],
                    "config": config,
                    "status": public_status(row, sampled_now=self.clock()),
                    "authority": authority,
                }
            self.sleep(min(0.02, max(0.0, self.context["deadline"] - self.clock())))

    def _reported_failure(self, caught):
        # A newer manual/STOP generation has priority even if the blocking
        # backend operation also overran the preparation budget. Never call
        # this an infrastructure timeout or replace it with an old run result.
        if isinstance(caught, TrialError) and caught.code == "navigation_trial_cancelled":
            return caught
        if isinstance(caught, TrialError) and caught.code in {
            "navigation_trial_prepare_timeout",
            "navigation_trial_stopped",
        }:
            try:
                self.guard()
            except TrialError as current:
                if current.code == "navigation_trial_cancelled":
                    return current
            except Exception:
                pass
        error = caught
        # A producer may already have run and stopped while systemd/start
        # bookkeeping was blocking. Its matching outcome is authoritative.
        if self.context["producer_not_before"] is not None:
            try:
                actual = self.matching_run()
            except Exception:
                actual = None
            if actual and actual.get("running") is False:
                error = TrialError(
                    "navigation_trial_stopped",
                    details={"started": True, "status": public_status(actual, fresh=False)},
                )
        return error

    def _cleanup_armed(self):
        if self.context["armed"]:
            # Each cleanup attempt is independent: a broken service
            # backend must not skip cancellation of a queued ARM.
            try:
                current = self.safety()
                if current.get("generation") != self.context.get("arm_generation"):
                    return  # New manual/STOP authority also owns its camera choice.
            except Exception:
                current = {}
            try:
                if not self.warm_reused:
                    self.manager.set_feature("s14_venom_navigation", False)
            except Exception:
                pass
            try:
                current = self.safety()
                if current.get("generation") == self.context.get("arm_generation") and current.get("owner") in {
                    None,
                    "navigation",
                }:
                    # Invalidate a delayed ARM too, even if its ACK has
                    # not arrived and the sampled executor is disarmed.
                    self.stop_old("navigation")
            except Exception:
                pass

    def _raise_failure(self, error, diagnostic):
        if isinstance(error, TrialError):
            error.details = {**(error.details or {}), "preparation": diagnostic}
            raise error from None
        from apps.compute.client import ComputeError

        if isinstance(error, ComputeError) and error.code == "navigation_journey_update_required":
            raise TrialError(error.code, 409, details={"preparation": diagnostic}) from error
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

    def run(self):
        with self.manager.operation(
            guard=self.guard,
            remaining=lambda: max(0.0, self.context["deadline"] - self.clock()),
            stop=self.stop_old,
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
                self._admit()
                config = self._prepare_sources()
                safety = self._arm_navigation()
                started = self._start_producer(safety)
                return self._await_status(config, started)
            except Exception as caught:
                error = self._reported_failure(caught)
                # Keep the passive reservation on failure, without restoring a
                # producer, ARM or drive after a newer operator STOP/takeover.
                diagnostic = self.progress(
                    self.context["phase"], "failed", getattr(error, "code", "navigation_trial_prepare_failed")
                )
                self._cleanup_armed()
                self._raise_failure(error, diagnostic)
