"""Only UART owner and actuator executor. Commands require explicit consent.

Passive tracking topics are deliberately not subscribed. Legacy actuator topic
names may carry the *same* authenticated envelope; bare legacy motion is refused.
"""

from __future__ import annotations

import logging
import uuid

from apps.motion import manual_settings
from apps.motion.actuator_contract import (
    COMMAND_TOPICS,
    SUB_TOPICS,
    decision_duration as decision_duration,
    decision_feedback_deadline as decision_feedback_deadline,
    validate_actuator as validate_actuator,
)  # public re-exports
from apps.motion.calibration_runtime import CalibrationRuntime
from apps.motion.dynamics import RampLimits
from apps.motion.executor_admission import ExecutorAdmission
from apps.motion.main import MotionController, _make_adapter
from apps.motion.operator_requests import OperatorRequests
from apps.motion.pulse_trials import PulseTrials
from apps.motion.sensor_quality import SensorSamples
from apps.safety.gate import ACTUATORS, MotionGate
from apps.safety.operator_control import ACTIONS as OPERATOR_ACTIONS
from apps.safety.state import write_status
from common.agent_control import is_agent, verify_command as verify_command
from common.motion_commands import canonical_command  # public re-export

LOG = logging.getLogger("motion.executor")


class MotionExecutor(ExecutorAdmission):
    def __init__(self, *, gate=None, adapter=None, publisher=None, status_writer=write_status):
        self.gate = gate or MotionGate()
        self.instance_id = uuid.uuid4().hex
        self.adapter = adapter if adapter is not None else _make_adapter(self.gate)
        self.controller = MotionController(self.adapter, self.gate)
        self.calibration = CalibrationRuntime(self.controller.limits)
        self.controller.limits = self.calibration.limits
        self.publisher = publisher
        self.status_writer = status_writer
        self.operator_requests = OperatorRequests()
        self.last_ack = None
        self.recent_acks = []
        self.pending = None
        self.last_snapshot = 0.0
        self.last_sensors = 0.0
        self.last_firmware = 0.0
        self.firmware = None
        self.sensor_values = {}
        self.sensor_times = {}
        self.sensor_index = 0
        self.samples = SensorSamples(
            self.gate.clock,
            self.gate.wall_clock,
            instance_id=self.instance_id,
            simulated=getattr(self.adapter, "simulated", False),
        )
        self.trials = PulseTrials(self)
        self.last_output = 0.0
        self.output_generation = None
        self.output_command_generation = None
        self.output_observed_at = None
        self.error = getattr(self.adapter, "error", None)
        self.controls = None
        self.controls_pending_revision = None
        self.controls_checked_at = 0.0
        self.shutdown = False
        self.intent_source = None
        self.execution_inhibit = None
        self.actuators = {
            "balance": {"enabled": None, "ts": None, "physical_completion": "unverified"},
            "height": {"value": None, "ts": None, "physical_completion": "unverified"},
        }
        # Controller deadline/watchdog stops use the same fault latch.
        self._controller_stop = self.controller.stop
        self.controller.stop = self._stop_hardware
        self.refresh_controls(force=True)
        self.controller.stop()
        self.publish_status(force=True)

    def _hardware_ready(self):
        error = getattr(self.adapter, "error", None)
        if error or not self.adapter.ok():
            self._hardware_fault(error or "hardware_unavailable")
        return bool(not self.shutdown and not self.error and self.adapter.ok())

    def _hardware_fault(self, reason, *, stop=True):
        # A later successful zero write never restores consent or readiness.
        # Recovery requires a newly initialized executor/adapter.
        self.error = self.error or reason
        if self.gate.state == "ARMED":
            self.gate.disarm("hardware_unavailable")
            if stop:
                self.controller.stop()

    def _stop_hardware(self):
        try:
            stopped = self._controller_stop() is True
        except Exception as exc:
            self._hardware_fault(f"hardware_stop_failed:{type(exc).__name__}", stop=False)
            self.output_observed_at = self.gate.wall_clock()
            self.output_command_generation = self.gate.generation
            self.publish_output(force=True, accepted=False)
            self.publish_status(force=True)
            return False
        if not stopped:
            self._hardware_fault(getattr(self.adapter, "error", None) or "hardware_stop_unconfirmed", stop=False)
        elif getattr(self.adapter, "error", None):
            self._hardware_fault(self.adapter.error, stop=False)
        self.output_observed_at = self.gate.wall_clock()
        self.output_command_generation = self.gate.generation
        self.publish_output(force=True, accepted=stopped)
        # A zero write remains valid while idle only with this exact executor
        # heartbeat. Deadline stops also need it before the output ages out.
        self.publish_status(force=True)
        return stopped

    def _publish(self, topic, payload):
        if self.publisher is not None:
            self.publisher.publish(topic, payload, add_ts=False)

    def refresh_controls(self, force=False):
        now = self.gate.clock()
        if not force and self.controls is not None and now - self.controls_checked_at < 0.2:
            return
        self.controls_checked_at = now
        if not self.controller.limits.valid:
            self._hardware_fault("invalid_motion_limits")
            return
        try:
            row = manual_settings.read(blocking=False)
            if self.controls is not None and row["revision"] != self.controls["revision"] and self.controller.deadline:
                # Published idle status can race an admitted goal. Keep that goal's
                # configuration until it ends, and admit no replacement on mixed revisions.
                self.controls_pending_revision = row["revision"]
                return
            self.controls_pending_revision = None
            values = row["values"]
            self.controller.limits = RampLimits(
                speed_limit=values["speed_limit"],
                linear_rate=values["linear_rate"],
                turn_rate=values["turn_rate"],
                linear_deceleration=values["linear_deceleration"],
                turn_deceleration=values["turn_deceleration"],
                reversal_pause=values["reversal_pause"],
                ramp_mode=values["ramp_mode"],
                watchdog_s=self.calibration.ceilings.watchdog_s,
                max_dt_s=self.calibration.ceilings.max_dt_s,
            )
            self.controls = row
        except BlockingIOError:
            return  # Keep dispatch responsive; command admission uses its own nonblocking lock.
        except (ValueError, OSError, TypeError):
            self._hardware_fault("manual_settings_unavailable")
            self.controls = None

    def snapshot(self):
        hardware_ready = self._hardware_ready()
        quality = self.samples.quality()
        ready = hardware_ready and quality["ready"] and self.controller.limits.valid
        state = self.gate.snapshot()
        state.update(
            authorization={
                "authority": "motion-executor",
                "state": state["state"],
                "generation": state["generation"],
                "instance_id": self.instance_id,
                "owner": state["owner"],
                "execution_context": state["execution_context"],
                "arming_mode": state["arming_mode"],
                "confirmed": True,
            },
            execution={
                "ready": ready,
                "inhibit": self.error or quality["error"],
                "motion_not_before": self.gate.motion_not_before,
            },
            manual_settings=self.controls,
            deadline=self.controller.deadline,
            remote_decision_deadline_supported=True,
            remote_decision_feedback_supported=True,
            scoped_stop_generation_supported=True,
            contract_id="rider.safety",
            observed_at=self.gate.wall_clock(),
            ts=self.gate.wall_clock(),
            ready=ready,
            hardware_ready=hardware_ready,
            hardware_initialized=bool(self.adapter.ok()),
            can_move=bool(ready and self.gate.can_actuate()),
            read_only=not bool(ready and self.gate.can_actuate()),
            error=self.error
            or getattr(self.adapter, "error", None)
            or quality["error"]
            or self.controller.limits.status()["error"],
            last_ack=self.last_ack,
            recent_acks=list(self.recent_acks),
            simulated=bool(getattr(self.adapter, "simulated", False)),
            moving=not self.controller.stopped,
            pulse_trials=self.trials.snapshot(),
            intent_mode=getattr(self.controller, "intent_mode", "pulse"),
            active_source=self.intent_source if self.controller.deadline > self.gate.clock() else None,
            agent_manual_active=bool(self.intent_source == 'manual' and self.controller.deadline > self.gate.clock()),
            target={"lx": self.controller.t_lx, "az": self.controller.t_az},
            output={"lx": self.controller.o_lx, "az": self.controller.o_az},
            uart_owner="motion-executor",
            instance_id=self.instance_id,
            physical_completion="unverified",
            capabilities=self.capabilities(),
            actuators=self.actuators,
            sensor_quality=quality,
            dynamics=self.controller.limits.status(),
            sdk_output=self.sdk_output(),
            calibration=dict(
                self.calibration.status(now=self.gate.wall_clock(), instance_id=self.instance_id),
                motion_settings=self.controls,
                motion_authority="device_settings",
            ),
        )
        return state

    def capabilities(self):
        ready = self._hardware_ready() and self.controller.limits.valid
        method = getattr(self.adapter, "capabilities", None)
        if callable(method):
            result = method()
            if not ready:
                return {name: {**value, "available": False} for name, value in result.items()}
            return result
        return {
            action: {
                "available": ready and action in {"move", "turn", "balance", "height"},
                "stop_verified": True,
                "verification": "simulated",
            }
            for action in {"move", "turn", "balance", "height", "action"}
        }

    def sdk_output(self, accepted=True):
        method = getattr(self.adapter, "output_status", None)
        output = method() if callable(method) else {"linear_step": None, "turn_step": None}
        return {
            **output,
            "contract_id": "rider.motion.output",
            "contract_version": 1,
            "observed_at": self.output_observed_at,
            "generation": self.output_command_generation,
            "accepted": bool(accepted and not self.error and self.adapter.ok()),
            "stopped": self.controller.stopped,
            "source": "motion-executor",
            "instance_id": self.instance_id,
            "physical_completion": "unverified",
        }

    def publish_output(self, *, force=False, accepted=True):
        now = self.gate.clock()
        if force or self.output_generation != self.gate.generation or now - self.last_output >= 0.1:
            self._publish("motion.output", self.sdk_output(accepted))
            self.last_output = now
            self.output_generation = self.gate.generation

    def publish_status(self, *, force=False):
        now = self.gate.clock()
        if force or now - self.last_snapshot >= 1.0:
            snapshot = self.snapshot()
            self.status_writer(snapshot)
            self._publish("motion.state", snapshot)
            self.last_snapshot = now

    def _ack(self, command, status, reason, **details):
        """Record command identity, requested maneuver and the current output without claiming physical completion."""
        self.last_ack = {
            "contract_id": "rider.motion.ack",
            "contract_version": 1,
            "request_id": command.get("request_id", command.get("rid")),
            "action": command.get("action"),
            "status": status,
            "reason": reason,
            "source": command.get("source"),
            "execution_context": command.get("execution_context"),
            "channel": command.get("channel"),
            "panel_id": command.get("panel_id"),
            "intent_id": command.get("intent_id"),
            "agent_epoch": command.get("agent_epoch"),
            "seq": command.get("seq"),
            "generation": self.gate.generation,
            "command_generation": command.get("generation"),
            "observed_at": self.gate.wall_clock(),
            "physical_completion": "unverified",
            "requested": {
                **{key: command.get(key) for key in ("direction", "vx", "yaw", "duration", "settings_revision")},
                **({"turn_mode": command["turn_mode"]} if "turn_mode" in command else {}),
            },
            "output": {"lx": self.controller.o_lx, "az": self.controller.o_az},
            "accepted": status in {"accepted", "executed"},
            "error": reason if status == "rejected" else None,
            **details,
        }
        self.operator_requests.observe(command, self.last_ack)
        if status in {"executed", "rejected"}:
            self.recent_acks.append(dict(self.last_ack))
            del self.recent_acks[:-16]
        self._publish("motion.ack", self.last_ack)
        self.publish_status(force=True)
        return dict(self.last_ack)

    def _begin_operator_request(self, payload, action):
        if (
            isinstance(payload, dict)
            and isinstance(payload.get("request_id"), str)
            and (action in OPERATOR_ACTIONS or action in {"move", "turn"} and payload.get("intervene") is True)
        ):
            previous = self.operator_requests.begin(payload)
            if previous is not None:
                return self._operator_replay(payload, previous)
        return None

    def _operator_replay(self, payload, previous):
        if previous.get("conflict"):
            return self._ack(payload, "rejected", "operator_request_conflict", operator_replay=True)
        ack = previous.get("ack")
        if ack:
            return self._ack(
                payload,
                ack["status"],
                ack["reason"],
                operator_replay=True,
                original_generation=ack["generation"],
                generation=ack["generation"],
            )
        return None

    def apply(self, payload, *, topic="motion.command"):
        # STOP must never wait for filesystem locks, profile reads or revisions.
        try:
            action = canonical_command(topic, payload).get("action")
        except (ValueError, TypeError, OverflowError):
            action = None
        replay = self._begin_operator_request(payload, action)
        if replay is not None:
            return replay
        if action in {"stop", "disarm", "estop"}:
            return self._apply(payload, topic=topic)
        try:
            with manual_settings.locked(blocking=False):
                if isinstance(payload, dict) and ("trial_profile_id" in payload or "trial_version" in payload):
                    return self.trials.admit(canonical_command(topic, payload))
                return self._apply(payload, topic=topic)
        except (OSError, ValueError, TypeError) as exc:
            return self._ack(payload if isinstance(payload, dict) else {}, "rejected", str(exc))

    def _apply(self, payload, *, topic="motion.command"):
        if topic == "calibration.activate":
            return self.calibration.activate(payload, self)
        if not isinstance(payload, dict) or topic not in COMMAND_TOPICS:
            return self._ack({}, "rejected", "passive_or_invalid_command")
        try:
            command = canonical_command(topic, payload)
        except (TypeError, ValueError, OverflowError):
            # Invalid aliases still use validation/cancellation, never escape dispatch.
            command = {**payload, "action": "move", "duration": None}
        action = command.get("action")
        panel_error = self.gate.panel_rejection(command)
        if panel_error:
            return self._ack(command, "rejected", panel_error)
        agent = is_agent(command)
        mode = command.get("mode", "pulse")
        if "operator_intervention_version" in command and mode == "release":
            return self._release_intervention(command)
        rejection = self._check_agent(command, action, agent)
        if rejection is not None:
            return rejection
        rejection = self._prepare_command(command, action, mode)
        if rejection is not None:
            return rejection
        is_actuator = isinstance(action, str) and action in ACTUATORS
        self._expire_previous_goal(action)
        values, rejection = self._validated_intent(command, action, mode, is_actuator, agent)
        if rejection is not None:
            return rejection
        reason, rejection = self._authorize_intent(command, action, is_actuator, agent)
        if rejection is not None:
            return rejection
        return self._execute_authorized(command, action, values, mode, reason)

    def _inhibit_motion(self, reason):
        if self.execution_inhibit != reason:
            self.execution_inhibit = reason
            self.gate.cancel_motion(reason)
            previous, self.pending = self.pending, None
            self.controller.stop()
            if previous is not None:
                self._ack(previous, "rejected", reason)

    def _tick_controller(self, dt):
        try:
            executed = self.controller.tick(dt)
        except Exception as exc:
            self._hardware_fault(f"actuator_transport_failed:{type(exc).__name__}")
            self.controller.stop()
            executed = False
        return executed

    def _complete_pending(self, executed):
        if self.pending is not None and executed:
            pending, self.pending = self.pending, None
            self._ack(pending, "executed", "sdk_accepted")
        elif self.pending is not None and not self.controller.deadline:
            pending, self.pending = self.pending, None
            reason = self.gate.reason if self.gate.state != "ARMED" else "goal_expired_before_execution"
            self._ack(pending, "rejected", reason)

    def tick(self, dt):
        if not self.controller.deadline:
            self.refresh_controls()
        generation = self.gate.generation
        self._hardware_ready()
        self.gate.poll()
        quality = self.samples.quality()
        if self.gate.state == "ARMED" and not quality["ready"]:
            self._inhibit_motion(quality["error"])
        elif quality["ready"]:
            self.execution_inhibit = None
        if generation != self.gate.generation:
            pending, self.pending = self.pending, None
            self.controller.stop()
            if pending is not None:
                self._ack(pending, "rejected", self.gate.reason)
            self.publish_status(force=True)
        self.trials.guard()
        executed = self._tick_controller(dt)
        if self.gate.reason == "actuator_failed":
            self._hardware_fault(getattr(self.adapter, "error", None) or "actuator_failed")
        if executed:
            self.output_observed_at = self.gate.wall_clock()
            self.output_command_generation = self.gate.generation
            self.publish_output()
        self._complete_pending(executed)
        self.trials.tick()
        self.publish_status()

    def process_batch(self, messages):
        commands = [
            (topic, payload) for topic, payload in messages if topic in COMMAND_TOPICS and isinstance(payload, dict)
        ]
        stops = [
            (topic, payload)
            for topic, payload in commands
            if isinstance(canonical_command(topic, payload).get("action"), str)
            and canonical_command(topic, payload).get("action") in {"stop", "disarm", "estop"}
        ]
        if stops:
            # No goal in the same received burst is ever applied around STOP.
            # Preserve its ACK snapshot; cancellation events cannot hide it.
            for topic, payload in stops:
                self.apply(payload, topic=topic)
            return
        for topic, payload in commands:
            self.apply(payload, topic=topic)

    def poll_sensors(self):
        from apps.motion.telemetry_poll import poll

        poll(self)

    def close(self, reason="executor_shutdown"):
        self.trials.finish("cancelled", reason)
        self.shutdown = True
        self.pending = None
        self.gate.disarm(reason)
        try:
            self.controller.stop()
        finally:
            self.adapter.close()
            self.publish_status(force=True)


def main() -> int:
    from apps.motion.executor_runtime import run

    return run(MotionExecutor, SUB_TOPICS, COMMAND_TOPICS)


if __name__ == "__main__":
    raise SystemExit(main())
