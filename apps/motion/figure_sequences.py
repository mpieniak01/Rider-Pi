"""Manual figure runs on the existing executor tick and its exclusive UART owner."""

import copy
from collections import OrderedDict

from apps.motion.figure_recipes import HEARTBEAT_S, catalog, compile_recipe, fingerprint, validate_request


class FigureSequences:
    def __init__(self, executor):
        self.executor = executor
        self.current = None
        self.requests = OrderedDict()
        self.steps = []
        self.index = -1
        self.generation = None
        self.last_heartbeat = 0.0
        self.next_renewal = 0.0
        self.targets = {}

    @property
    def active(self):
        return self.current is not None and self.current["phase"] in {"preparing", "running"}

    def axes(self):
        adapter = self.executor.adapter
        method = getattr(adapter, "figure_axes", None)
        return (
            method()
            if callable(method)
            else {
                "height": callable(getattr(adapter, "set_height", None)),
                "roll": callable(getattr(adapter, "set_roll", None)),
            }
        )

    def snapshot(self):
        history = []
        for _, row in list(self.requests.values())[-4:]:
            if row is self.current:
                continue
            summary = {key: copy.deepcopy(value) for key, value in row.items() if key not in {"settings", "events"}}
            summary["events"] = copy.deepcopy(row["events"][-8:])
            summary["events_dropped"] = row.get("events_dropped", 0) + max(0, len(row["events"]) - 8)
            summary["evidence_partial"] = True
            history.append(summary)
        return {"version": 1, "axes": self.axes(), "current": copy.deepcopy(self.current), "history": history[-3:]}

    def _event(self, kind, **details):
        self.current["events"].append(
            {"kind": kind, "elapsed_ms": round((self.executor.gate.clock() - self.started) * 1000, 3), **details}
        )
        if len(self.current["events"]) > 96:
            self.current["events_dropped"] = self.current.get("events_dropped", 0) + 1
            self.current["events"] = self.current["events"][-96:]

    def _emit(self):
        self.executor._publish("motion.figure", copy.deepcopy(self.current))
        self.executor.publish_status(force=True)

    def admit(self, command):
        e = self.executor
        try:
            identifier = validate_request(command)
            if "figure_run_id" in command:
                return self.heartbeat(command)
            digest, request = fingerprint(command), command["request_id"]
            if request in self.requests:
                previous_digest, run = self.requests[request]
                if digest != previous_digest:
                    raise ValueError("figure_request_conflict")
                return e._ack(command, "executed", "figure_replay", figure_run_id=run["run_id"])
            if self.active or e.trials.active:
                raise ValueError("figure_active")
            e.gate.poll()
            if e.gate.state != "DISARMED" or not e.controller.stopped or e.controller.deadline:
                raise ValueError("figure_requires_idle")
            e.refresh_controls(force=True)
            if (
                e.controls is None
                or type(command.get("settings_revision")) is not int
                or e.controls["revision"] != command["settings_revision"]
            ):
                raise ValueError("manual_settings_stale")
            row = next(row for row in catalog(self.axes())["figures"] if row["id"] == identifier)
            if not row["available"]:
                raise ValueError(row["reason"])
            steps = compile_recipe(identifier, e.controls)
            rejection = e._actuator_ready(command, "move")
            if rejection is not None:
                return rejection
            authorized, reason = e.gate.authorize(command)
            if not authorized:
                return e._ack(command, "rejected", reason)
        except (ValueError, TypeError, OverflowError) as error:
            return e._ack(command, "rejected", str(error))
        self.started = self.last_heartbeat = e.gate.clock()
        self.generation, self.panel = e.gate.generation, command["panel_id"]
        self.not_before, self.steps, self.index = e.gate.motion_not_before, steps, -1
        self.settings = copy.deepcopy(e.controls)
        self.current = {
            "version": 1,
            "run_id": request,
            "figure_id": identifier,
            "recipe_version": 1,
            "phase": "preparing",
            "reason": "running",
            "generation": self.generation,
            "panel_id": self.panel,
            "settings_revision": command["settings_revision"],
            "settings": self.settings,
            "duration_ms": row["duration_ms"],
            "step": 0,
            "step_count": len(steps),
            "elapsed_ms": 0,
            "events": [],
            "physical_completion": "unverified",
            "implementation": "own_sequence",
        }
        self.requests[request] = digest, self.current
        while len(self.requests) > 8:
            self.requests.popitem(last=False)
        self.targets = {key: item.get("value") for key, item in e.actuators.items() if key in {"height", "roll"}}
        e.intent_source = "manual"
        self._event("started")
        self._emit()
        return e._ack(command, "executed", "figure_started", figure_run_id=request)

    def heartbeat(self, command):
        e = self.executor
        if not self.active or command["figure_run_id"] != self.current["run_id"]:
            return e._ack(command, "rejected", "figure_run_inactive")
        if command["figure_id"] != self.current["figure_id"] or command["panel_id"] != self.panel:
            return e._ack(command, "rejected", "figure_run_mismatch")
        if e.gate.state != "ARMED" or e.gate.generation != self.generation:
            return e._ack(command, "rejected", "figure_authority_changed")
        if e.gate.clock() - self.last_heartbeat >= HEARTBEAT_S:
            self.finish("cancelled", "figure_contact_lost")
            return e._ack(command, "rejected", "figure_run_inactive")
        if command.get("settings_revision") != self.current["settings_revision"]:
            return e._ack(command, "rejected", "manual_settings_stale")
        authorized, reason = e.gate.authorize(command)
        if authorized:
            self.last_heartbeat = e.gate.clock()
        return e._ack(
            command,
            "executed" if authorized else "rejected",
            "figure_keepalive" if authorized else reason,
            figure_run_id=self.current["run_id"],
        )

    def finish(self, phase, reason, *, stop=True, disarm=True):
        if not self.active:
            return
        e = self.executor
        owns = e.gate.generation == self.generation and e.gate.owner == "manual"
        self.current.update(phase=phase, reason=reason)
        self._event(phase)
        if owns and stop and not e.controller.stop():
            self.current.update(phase="failed", reason="hardware_stop_unconfirmed")
        if owns and disarm:
            e.gate.disarm("figure_" + self.current["phase"])
            e.intent_source = None
        self._emit()

    def override(self):
        self.finish("cancelled", "operator_intervention", disarm=False)

    def _guard(self, dt):
        e, now = self.executor, self.executor.gate.clock()
        if e.gate.generation != self.generation or e.gate.state != "ARMED" or e.gate.owner != "manual":
            self.finish("cancelled", "authority_changed", stop=False, disarm=False)
            return False
        if now - self.last_heartbeat >= HEARTBEAT_S:
            self.finish("cancelled", "figure_contact_lost")
            return False
        if not e.controller.limits.valid or not 0 < dt <= e.controller.limits.max_dt_s:
            self.finish("failed", "control_timing_invalid")
            return False
        if (
            e.error
            or not e.samples.quality()["ready"]
            or e.controls_pending_revision is not None
            or e.controls is None
            or e.controls["revision"] != self.current["settings_revision"]
            or e.gate.motion_not_before != self.not_before
        ):
            self.finish("failed", "figure_motion_inhibited")
            return False
        if (now - self.started) * 1000 > self.current["duration_ms"] + 500:
            self.finish("failed", "figure_deadline")
            return False
        return True

    def _begin_step(self, now):
        e = self.executor
        if not e.controller.stop():
            self.finish("failed", "hardware_stop_unconfirmed")
            return False
        self.index += 1
        if self.index >= len(self.steps):
            self.finish("completed", "sequence_completed")
            return False
        planned = self.started if self.index == 0 else self.step_started + self.steps[self.index - 1]["ms"] / 1000
        self.step_started, self.next_renewal = min(planned, now), now
        self.origins = dict(self.targets)
        self.current.update(phase="running", step=self.index + 1)
        self._event("step_started", step=self.index + 1, target=dict(self.steps[self.index]))
        self._emit()
        return True

    def _posture(self, row, fraction):
        e = self.executor
        blend = fraction * fraction * (3 - 2 * fraction)
        for axis in ("height", "roll"):
            if axis not in row:
                continue
            origin = self.origins.get(axis)
            origin = row[axis] if origin is None else origin
            value = origin + (row[axis] - origin) * blend
            value = round(value) if axis == "height" else round(value, 1)
            if self.targets.get(axis) == value:
                continue
            method = getattr(e.adapter, "set_" + axis, None)
            if not callable(method) or method(value) is False:
                self.finish("failed", "figure_posture_failed")
                return False
            self.targets[axis] = value
            e.actuators[axis] = {"value": value, "ts": e.gate.wall_clock(), "physical_completion": "unverified"}
            self._event("posture", axis=axis, value=value)
        return True

    def tick(self, dt):
        if not self.active or not self._guard(dt):
            return
        e, now = self.executor, self.executor.gate.clock()
        if self.index < 0 and not self._begin_step(now):
            return
        row = self.steps[self.index]
        fraction = min(1.0, (now - self.step_started) * 1000 / row["ms"])
        if not self._posture(row, fraction):
            return
        if fraction >= 1:
            if not self._begin_step(now):
                return
            row = self.steps[self.index]
        if (row["vx"] or row["yaw"]) and now >= self.next_renewal:
            if not e.controller.drive(
                row["vx"],
                row["yaw"],
                0.5,
                panel_pulse=True,
                mode="hold",
                turn_in_place=row["vx"] == 0 and row["yaw"] != 0,
            ):
                self.finish("failed", "figure_goal_rejected")
                return
            self.next_renewal = now + 0.15
        self.current["elapsed_ms"] = round((now - self.started) * 1000, 3)
