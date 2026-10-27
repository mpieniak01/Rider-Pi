"""Ordered admission and actuation stages for the sole motion executor."""

from apps.motion import manual_settings
from apps.motion.actuator_contract import (
    bounded_navigation,
    decision_duration,
    decision_feedback_deadline,
    validate_actuator,
)
from apps.safety.gate import ACTUATORS
from apps.safety.operator_control import ACTIONS as OPERATOR_ACTIONS
from common.agent_control import verify_command


class ExecutorAdmission:
    def _release_intervention(self, command):
        try:
            matching = self.gate.manual_intervention.release(command)
        except ValueError as exc:
            return self._ack(command, "rejected", str(exc))
        if matching:
            self.intent_source = None
            previous, self.pending = self.pending, None
            stopped = self.controller.stop()
            if previous is not None:
                self._ack(
                    previous, "rejected", "operator_intervention_cancelled", cancelled_by=command.get("request_id")
                )
            return self._ack(
                command,
                "executed" if stopped else "rejected",
                "operator_intervention_released" if stopped else "hardware_stop_unconfirmed",
                hardware_stop_sent=stopped,
            )
        return self._ack(command, "executed", "operator_intervention_cancelled", hardware_stop_sent=False)

    def _check_agent(self, command, action, agent):
        if agent and action not in {'stop', 'disarm', 'estop'}:
            try:
                verify_command(command)
                if self.intent_source == 'manual' and self.controller.deadline > self.gate.clock():
                    raise ValueError('agent_manual_priority')
            except ValueError as exc:
                return self._ack(command, 'rejected', str(exc))
        return None

    def _check_motion_mode(self, command, action, mode):
        if action in {"move", "turn"}:
            if not isinstance(mode, str) or mode not in {"pulse", "hold", "release"}:
                return self._ack(command, "rejected", "unsupported_motion_mode")
            if mode != "pulse" and not (
                command.get("device_settings") is True
                and command.get("source") == "manual"
                and command.get("execution_context") == "panel"
                and (
                    command.get("operator_intervention_version") == 1
                    or (self.gate.arming_mode == "operator" or self.gate.operator_control.enabled)
                    and self.gate.execution_context == "panel"
                )
                and (self.gate.owner == "manual" or command.get("intervene") is True)
            ):
                return self._ack(command, "rejected", "hold_operator_panel_only")
        return None

    def _prepare_command(self, command, action, mode):
        rejection = self._check_motion_mode(command, action, mode)
        if rejection is not None:
            return rejection
        if action in {"arm", "move", "turn", "height", "balance", "stabilization", "action"} | OPERATOR_ACTIONS:
            if not self.controller.limits.valid:
                self._hardware_fault("invalid_motion_limits")
            self.refresh_controls(force=True)
        if action in {"move", "turn", "height", "balance", "stabilization", "action"} | OPERATOR_ACTIONS:
            if self.controls_pending_revision is not None:
                return self._ack(command, "rejected", "manual_settings_requires_idle")
            if (
                self.controls is None
                or type(command.get("settings_revision")) is not int
                or command["settings_revision"] != self.controls["revision"]
            ):
                return self._ack(command, "rejected", "manual_settings_stale")
            return self._resolve_direction(command, action, mode)
        return None

    def _resolve_direction(self, command, action, mode):
        if action in {"move", "turn"} and "direction" in command:
            try:
                expected = manual_settings.pulse(self.controls, command["direction"])
                if command.get("device_settings") is True:
                    command.update(expected)
                    if mode in {"hold", "release"}:
                        command["duration"] = manual_settings.HOLD_TIMEOUT_S
                    if mode == "release":
                        command.update(vx=0.0, yaw=0.0)
                elif any(command.get(key) != value for key, value in expected.items()):
                    return self._ack(command, "rejected", "manual_settings_mismatch")
            except ValueError as exc:
                return self._ack(command, "rejected", str(exc))

        return None

    def _expire_previous_goal(self, action):
        self.controller.expire_remote_decision()
        if (
            isinstance(action, str)
            and action not in {"stop", "disarm", "estop"}
            and self.controller.deadline
            and self.gate.clock() >= self.controller.deadline
        ):
            self.controller.expire_goal()
            if self.pending is not None:
                previous, self.pending = self.pending, None
                self._ack(previous, "rejected", "motion_goal_timeout")

    def _validated_intent(self, command, action, mode, is_actuator, agent):
        try:
            values = validate_actuator(command)
            if action in {"move", "turn"} and not bounded_navigation(command):
                manual_settings.validate_command(self.controls, values, mode=mode)
        except ValueError as exc:
            self._cancel_invalid_intent(command, is_actuator, agent)
            return None, self._ack(command, "rejected", str(exc))
        return values, None

    def _cancel_invalid_intent(self, command, is_actuator, agent):
        if is_actuator and self.controller.deadline and not agent:
            self.gate.cancel_motion("invalid_motion_intent")
            self.controller.stop()
            previous, self.pending = self.pending, None
            if previous is not None:
                self._ack(previous, "rejected", "invalid_motion_intent", cancelled_by=command.get("request_id"))

    def _stop_transferred_intent(self, command):
        """Retire the previous intent and stop before acknowledging new authority."""
        previous, self.pending = self.pending, None
        self.intent_source = None
        stopped = self.controller.stop()
        if previous is not None:
            self._ack(previous, "rejected", "operator_intervention", cancelled_by=command.get("request_id"))
        return stopped

    def _authorize_intent(self, command, action, is_actuator, agent):
        previous_generation = self.gate.generation
        authorized, reason = self.gate.authorize(command)
        if not authorized:
            if previous_generation != self.gate.generation and reason == "navigation_journey_manual_arm_required":
                stopped = self._stop_transferred_intent(command)
                return reason, self._ack(
                    command,
                    "rejected",
                    reason if stopped else "hardware_stop_unconfirmed",
                    gate_reason=reason,
                    hardware_stop_sent=stopped,
                )
            # Delayed renewals never undo a newer manual intent or release.
            obsolete = reason in {
                "stale_sequence",
                "stale_generation",
                "expired_command",
                "motion_intent_cancelled",
                "panel_owner_mismatch",
                "invalid_panel_id",
                "operator_control_not_available",
                "operator_panel_required",
                "navigation_operation_stale",
                "operator_intervention_cancelled",
                "operator_intervention_stale",
            }
            if not obsolete:
                self._cancel_invalid_intent(command, is_actuator, agent)
            return reason, self._ack(command, "rejected", reason)
        if previous_generation != self.gate.generation and action not in {"stop", "disarm", "estop", "clear_estop"}:
            stopped = self._stop_transferred_intent(command)
            if not stopped:
                self.gate.disarm("hardware_stop_unconfirmed")
                return reason, self._ack(command, "rejected", "hardware_stop_unconfirmed")
        return reason, None

    def _execute_authorized(self, command, action, values, mode, reason):
        self.trials.override()
        if action in OPERATOR_ACTIONS:
            return self._ack(command, "executed", reason, hardware_stop_sent=True)
        if action in {"stop", "disarm", "estop", "clear_estop"}:
            return self._execute_stop(command, action, reason)
        if action == "arm":
            return self._execute_arm(command)
        rejection = self._actuator_ready(command, action)
        if rejection is not None:
            return rejection
        if action in {"move", "turn"}:
            return self._execute_motion(command, values, mode)
        return self._execute_posture(command, action, values)

    def _execute_stop(self, command, action, reason):
        self.intent_source = None
        pending, self.pending = self.pending, None
        stopped = self.controller.stop()
        if pending is not None:
            self._ack(pending, "rejected", f"cancelled_by_{action}", cancelled_by=command.get("request_id"))
        # Ostatni ACK pozostaje ACK zatrzymania, wcześniejszy cel ma osobny
        # terminalny wpis w ledgerze zamiast wiecznego pending.
        return self._ack(
            command,
            "executed" if stopped else "rejected",
            reason if stopped else "hardware_stop_unconfirmed",
            gate_reason=reason,
            hardware_stop_sent=stopped,
        )

    def _execute_arm(self, command):
        if not self._hardware_ready():
            self.gate.disarm("hardware_unavailable")
            return self._ack(command, "rejected", "hardware_unavailable")
        if not self.controller.limits.valid:
            self.gate.disarm("invalid_motion_limits")
            self.controller.stop()
            return self._ack(command, "rejected", "invalid_motion_limits")
        return self._ack(command, "executed", "armed_no_actuation")

    def _actuator_ready(self, command, action):
        if action not in ACTUATORS:
            return None
        if not self._hardware_ready():
            if command.get("operator_intervention_version") == 1:
                self.gate.disarm("hardware_unavailable")
            self.controller.stop()
            return self._ack(command, "rejected", "hardware_unavailable")
        quality = self.samples.quality()
        if not quality["ready"] or not self.controller.limits.valid:
            reason = quality["error"] or "invalid_motion_limits"
            self._inhibit_motion(reason)
            return self._ack(command, "rejected", reason)
        capability = self.capabilities().get("balance" if action == "stabilization" else action, {})
        if not capability.get("available") or (
            action not in {"height", "balance", "stabilization"} and not capability.get("stop_verified")
        ):
            return self._ack(command, "rejected", "manual_characterization_required")
        self._manual_takeover(command, action)
        return None

    def _manual_takeover(self, command, action):
        if command.get('source') == 'manual' and self.intent_source == 'agent' and action not in {'move', 'turn'}:
            previous, self.pending = self.pending, None
            self.controller.stop()
            self.intent_source = None
            if previous is not None:
                self._ack(previous, 'rejected', 'manual_takeover', cancelled_by=command.get('request_id'))

    def _execute_motion(self, command, values, mode):
        """Submit an authorized goal with its original deadlines and optional in-place mode."""
        journey = self.gate.arming_mode == "journey"
        try:
            now = self.gate.clock()
            values["duration"] = decision_duration(command, values["duration"], now)
            feedback = decision_feedback_deadline(
                command,
                now,
                timed_navigation=self.gate.owner == "navigation"
                and self.gate.execution_context == "panel"
                and self.gate.arming_mode in {"timed", "journey"},
            )
        except ValueError as exc:
            if journey:
                self.gate.disarm(str(exc))
                self.controller.stop()
            return self._ack(command, "rejected", str(exc))
        if not self.controller.drive(
            values["vx"],
            values["yaw"],
            values["duration"],
            panel_pulse=command.get("device_settings") is True,
            mode=mode,
            remote_decision_deadline=command.get("decision_deadline_monotonic"),
            remote_feedback_deadline=feedback,
            **({"turn_in_place": True} if command.get("turn_mode") == "in_place" else {}),
        ):
            if journey:
                self.gate.disarm("motion_submission_failed")
                self.controller.stop()
            return self._ack(command, "rejected", "motion_disarmed")
        try:
            self.gate.journey.accepted_goal(command, feedback)
        except ValueError as exc:
            self.gate.disarm(str(exc))
            self.controller.stop()
            return self._ack(command, "rejected", str(exc))
        if values["vx"] != 0 or values["yaw"] != 0:
            self.gate.operator_control.activated(command)
        previous, self.pending = self.pending, None
        self.intent_source = command.get('source')
        if previous is not None:
            self._ack(previous, "rejected", "goal_superseded", superseded_by=command.get("request_id"))
        if (
            values["vx"] == 0
            and values["yaw"] == 0
            and (mode != "release" or self.controller.stopped and not self.controller.deadline)
        ):
            self.output_observed_at = self.gate.wall_clock()
            self.publish_output(force=True)
            return self._ack(command, "executed", "sdk_zero_accepted")
        self.pending = command
        return self._ack(command, "accepted", "goal_accepted")

    def _execute_posture(self, command, action, values):
        method, argument = {
            "balance": ("enable_balance", values.get("enabled")),
            "stabilization": ("enable_balance", values.get("enabled")),
            "height": ("set_height", values.get("height")),
            "action": ("action", values.get("name")),
        }[action]
        if getattr(self.adapter, method)(argument):
            if action in {"balance", "height"}:
                key = "enabled" if action == "balance" else "value"
                self.actuators[action] = {
                    key: command.get(key if action == "balance" else "height"),
                    "ts": self.gate.wall_clock(),
                    "physical_completion": "unverified",
                }
            return self._ack(command, "executed", "sdk_accepted")
        self._hardware_fault(getattr(self.adapter, "error", None) or "actuator_failed")
        self.gate.disarm("actuator_failed")
        self.controller.stop()
        return self._ack(command, "rejected", "actuator_failed")
