"""A bounded manual experiment inside the sole executor, using its existing tick."""

import copy
import hashlib
import json
from collections import OrderedDict

from apps.motion import manual_settings
from apps.motion.trial_profiles import MAX_RUN_S, common_settings, recipe

ACTIVE = {"pulse", "gap"}


class PulseTrials:
    def __init__(self, executor):
        self.executor = executor
        self.current = None
        self.requests = OrderedDict()
        self.next_at = 0.0
        self.started = 0.0
        self.generation = None

    @property
    def active(self):
        return self.current is not None and self.current["phase"] in ACTIVE

    def _elapsed(self):
        return round(max(0.0, self.executor.gate.clock() - self.started) * 1000, 3)

    def snapshot(self):
        row = copy.deepcopy(self.current)
        if row and self.active:
            row["elapsed_ms"] = self._elapsed()
        history = [copy.deepcopy(run) for _, run in self.requests.values() if run is not self.current]
        return {"version": 1, "current": row, "history": history[-3:]}

    def _event(self, kind):
        self.current["events"].append(
            {"kind": kind, "pulse_index": self.current["pulse_index"], "elapsed_ms": self._elapsed()}
        )
        self.current["elapsed_ms"] = self._elapsed()

    def _emit(self):
        self.executor._publish("motion.trial", copy.deepcopy(self.current))

    def admit(self, command):
        executor = self.executor
        identity = hashlib.sha256(json.dumps(command, sort_keys=True, allow_nan=False).encode()).hexdigest()
        request = command.get("request_id")
        if not isinstance(request, str) or not request.strip() or len(request) > 128:
            return executor._ack(command, "rejected", "request_id_required")
        if request in self.requests:
            fingerprint, previous = self.requests[request]
            if identity != fingerprint:
                return executor._ack(command, "rejected", "pulse_trial_request_conflict")
            return executor._ack(
                command, "executed", "pulse_trial_replay", pulse_trial_id=previous["run_id"], operator_replay=True
            )
        try:
            plan = recipe(command)
            if self.active or executor.figures.active:
                raise ValueError("pulse_trial_active")
            executor.gate.poll()
            if executor.gate.state != "DISARMED" or not executor.controller.stopped or executor.controller.deadline:
                raise ValueError("pulse_trial_requires_idle")
            executor.refresh_controls(force=True)
            controls = executor.controls
            if (
                controls is None
                or type(command.get("settings_revision")) is not int
                or controls["revision"] != command["settings_revision"]
            ):
                raise ValueError("manual_settings_stale")
            values = manual_settings.pulse(controls, "forward")
            if abs(values["duration"] * 1000 - plan["pulse_ms"]) > 0.000001 or values["vx"] <= 0:
                raise ValueError("pulse_trial_settings_mismatch")
            manual_settings.validate_command(controls, values)
            rejection = executor._actuator_ready(command, "move")
            if rejection is not None:
                return rejection
            baseline, group = common_settings(
                controls, command.get("trial_context", ""), copy.deepcopy(executor.actuators)
            )
            authorized, reason = executor.gate.authorize(command)
            if not authorized:
                return executor._ack(command, "rejected", reason)
        except (ValueError, TypeError, OverflowError) as error:
            return executor._ack(command, "rejected", str(error))
        self.started = executor.gate.clock()
        self.generation = executor.gate.generation
        self.not_before = executor.gate.motion_not_before
        self.current = {
            "version": 1,
            "run_id": request,
            "profile_id": plan["id"],
            "profile_version": 1,
            "count": plan["count"],
            "pulse_ms": plan["pulse_ms"],
            "gap_ms": plan["gap_ms"],
            "direction": "forward",
            "settings_revision": controls["revision"],
            "generation": self.generation,
            "group_id": group,
            "common": baseline,
            "phase": "pulse",
            "reason": "running",
            "pulse_index": 0,
            "completed_pulses": 0,
            "elapsed_ms": 0.0,
            "events": [],
            "physical_completion": "unverified",
        }
        self.requests[request] = identity, self.current
        while len(self.requests) > 8:
            self.requests.popitem(last=False)
        executor.intent_source = "manual"
        if not self._pulse():
            return executor._ack(command, "rejected", "pulse_trial_submission_failed")
        executor.publish_status(force=True)
        return executor._ack(command, "executed", "pulse_trial_started", pulse_trial_id=request)

    def _pulse(self):
        executor = self.executor
        self.current["phase"] = "pulse"
        self.current["pulse_index"] += 1
        self.output_started = False
        if not executor.controller.drive(
            self.current["common"]["parameters"]["speed"], 0.0, self.current["pulse_ms"] / 1000, panel_pulse=True
        ):
            self.finish("failed", "pulse_trial_submission_failed")
            return False
        self._event("pulse_started")
        self._emit()
        return True

    def finish(self, phase, reason, *, stop=True, disarm=True):
        if not self.active:
            return
        executor = self.executor
        owns = executor.gate.generation == self.generation and executor.gate.owner == "manual"
        self.current.update(phase=phase, reason=reason)
        self._event(phase)
        if owns and stop:
            stopped = executor.controller.stop()
            if not stopped:
                self.current.update(phase="failed", reason="hardware_stop_unconfirmed")
        if owns and disarm:
            executor.gate.disarm("pulse_trial_" + self.current["phase"])
            executor.intent_source = None
        self._emit()
        executor.publish_status(force=True)

    def override(self):
        self.finish("cancelled", "operator_intervention", disarm=False)

    def guard(self):
        if not self.active:
            return False
        executor = self.executor
        if (
            executor.gate.generation != self.generation
            or executor.gate.state != "ARMED"
            or executor.gate.owner != "manual"
        ):
            self.finish("cancelled", "authority_changed", stop=False, disarm=False)
            return False
        if self._elapsed() >= MAX_RUN_S * 1000:
            self.finish("failed", "pulse_trial_deadline")
            return False
        if (
            executor.gate.motion_not_before != self.not_before
            or not executor.samples.quality()["ready"]
            or not executor.controller.limits.valid
        ):
            self.finish("failed", "pulse_trial_motion_cancelled")
            return False
        if executor.error or getattr(executor.adapter, "error", None):
            self.finish("failed", "hardware_unavailable")
            return False
        if executor.controls is None or executor.controls["revision"] != self.current["settings_revision"]:
            self.finish("failed", "manual_settings_stale")
            return False
        return True

    def tick(self):
        if not self.guard():
            return
        executor = self.executor
        if self.current["phase"] == "gap":
            if executor.gate.clock() >= self.next_at:
                self._pulse()
            return
        if not self.output_started and not executor.controller.stopped:
            self.output_started = True
            self._event("output_started")
        if not executor.controller.deadline and executor.controller.stopped:
            if not executor.sdk_output().get("accepted"):
                self.finish("failed", "hardware_stop_unconfirmed")
                return
            self.current["completed_pulses"] += 1
            self._event("pulse_zero")
            if self.current["completed_pulses"] == self.current["count"]:
                self.finish("completed", "completed")
            else:
                self.current["phase"] = "gap"
                self.next_at = executor.gate.clock() + self.current["gap_ms"] / 1000
                self._event("gap_started")
                self._emit()
