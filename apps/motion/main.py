"""Shared motion controller. The only process entry point is the executor."""

from __future__ import annotations

import os

from apps.motion.dynamics import CurveRamp, RampLimits, approach, curve_factor, finite
from apps.motion.limits import MAX_SPEED
from apps.motion.manual_settings import MAX_PANEL_DURATION_S
from apps.safety.estop import estop_triggered as estop_triggered, motion_enabled as motion_enabled
from apps.safety.gate import MAX_DURATION_S, MotionGate

DYNAMICS = RampLimits.from_env()
WATCHDOG_MS = DYNAMICS.watchdog_s * 1000
LOOP_DT = 0.02
SPEED_LIMIT = DYNAMICS.speed_limit
RAMP_LX = DYNAMICS.linear_rate
RAMP_AZ = DYNAMICS.turn_rate
EPS = 0.001


class _SimAdapter:
    simulated = True
    error = None

    def __init__(self):
        self._moving = False

    def ok(self):
        return True

    def move(self, lx=0.0, az=0.0):
        self._moving = bool(lx or az)
        return True

    def stop(self):
        self._moving = False
        return True

    def get_imu(self):
        return None

    def battery(self):
        return None

    def firmware(self):
        return None

    def enable_balance(self, enabled):
        """Accept the adapter call without hardware effects.

        enabled is intentionally unused: MotionExecutor shares this callable
        interface between simulated and physical adapters. A simulation accepts
        the call without claiming a physical balance state or motion authority.
        """
        return True

    def set_height(self, height):
        """Accept the adapter call without fabricating a physical measurement.

        height is intentionally unused: MotionExecutor uses the same public
        keyword contract for both adapters; this no-I/O implementation cannot
        observe or change a robot's height.
        """
        return True

    def action(self, name):
        """Reject every named action in the simulator.

        name is intentionally unused: MotionExecutor shares this keyword
        contract with the physical adapter, but no scripted action is simulated.
        """
        return False

    def close(self):
        self.stop()


class _RealAdapter:
    simulated = False

    def __init__(self, gate: MotionGate):
        from drivers.xgo import XgoAdapter

        self._ada = XgoAdapter(gate=gate, owner=True)

    @property
    def error(self):
        return self._ada.error

    def ok(self):
        return self._ada.ok()

    def capabilities(self):
        return self._ada.capabilities()

    def move(self, lx=0.0, az=0.0):
        # yaw<0 is left, matching HTTP and tracking controllers.
        yaw = self._ada.spin("left" if az < 0 else "right", abs(az))
        linear = self._ada.drive("forward" if lx >= 0 else "backward", abs(lx))
        return bool(yaw and linear)

    def stop(self):
        return self._ada.stop()

    def get_imu(self):
        return self._ada.imu()

    extended_sensor_reads = False

    def read_sensor(self, name):
        if name == "battery":
            return self._ada.battery()
        if name == "firmware":
            value = self._ada.firmware()
            self.extended_sensor_reads = value == "R-1.1.6"
            return value
        if name in {"imu_packet", "work_status"}:
            return self._ada.read_extended_sensor(name)
        return self._ada.read_axis(name)

    def battery(self):
        return self._ada.battery()

    def firmware(self):
        return self._ada.firmware()

    def enable_balance(self, enabled):
        return self._ada.enable_balance(enabled)

    def set_height(self, height):
        return self._ada.set_height(height)

    def action(self, name):
        return self._ada.action(name)

    def close(self):
        self._ada.close()

    def output_status(self):
        return self._ada.output_status()


def _make_adapter(gate: MotionGate | None = None):
    if os.getenv("RIDER_SIMULATOR") == "1" or os.getenv("RIDER_TEST_ISOLATED") == "1":
        return _SimAdapter()
    # Missing hardware never becomes a successful simulation in production.
    return _RealAdapter(gate or MotionGate())


class MotionController:
    def __init__(self, robot, gate: MotionGate | None = None, *, limits=None):
        """Initialize ramp state and deadlines without granting motion authority."""
        self.curves = [CurveRamp(), CurveRamp()]
        self.curve_braking = [False, False]
        self.turn_in_place = False
        self.robot = robot
        self.gate = gate or MotionGate()
        self.limits = limits or DYNAMICS
        self.last_cmd_ts = 0.0
        self.deadline = 0.0
        self.remote_decision_deadline = None
        self.remote_feedback_deadline = None
        self.stopped = True
        self.t_lx = self.t_az = self.o_lx = self.o_az = 0.0
        self.reversing = False
        self.reverse_until = None

    def _stop_immediate(self):
        """Clear all targets and ramp state before issuing the hardware stop."""
        for curve in self.curves:
            curve.reset()
        self.curve_braking = [False, False]
        self.turn_in_place = False
        self.t_lx = self.t_az = self.o_lx = self.o_az = 0.0
        self.reversing = False
        self.reverse_until = None
        self.deadline = self.last_cmd_ts = 0.0
        self.remote_decision_deadline = None
        self.remote_feedback_deadline = None
        self.stopped = True
        return self.robot.stop()

    stop = _stop_immediate

    def drive(
        self,
        lx: float,
        az: float,
        duration: float = MAX_DURATION_S,
        *,
        panel_pulse=False,
        mode="pulse",
        remote_decision_deadline=None,
        remote_feedback_deadline=None,
        turn_in_place=False,
    ):
        """Accept a bounded target, distinguishing operator pulses from timed manual goals."""
        if not self.limits.valid or not self.gate.can_actuate():
            self.stop()
            return False
        manual_panel = bool(panel_pulse and self.gate.owner == "manual" and self.gate.execution_context == "panel")
        panel_pulse = self._operator_panel_pulse(panel_pulse)
        if (
            not isinstance(mode, str)
            or mode not in {"pulse", "hold", "release"}
            or (mode != "pulse" and not panel_pulse)
        ):
            return False
        if turn_in_place and (not manual_panel or lx != 0):
            return False
        self.intent_mode = mode
        duration_limit = MAX_PANEL_DURATION_S if panel_pulse else MAX_DURATION_S
        if (
            not all(finite(value) for value in (lx, az, duration))
            or max(abs(lx), abs(az)) > 1
            or not 0 < duration <= duration_limit
        ):
            self.gate.disarm("invalid_motion_intent")
            self.stop()
            return False
        navigation = (
            remote_decision_deadline is not None
            and self.gate.owner == "navigation"
            and self.gate.execution_context == "panel"
        )
        if max(abs(lx), abs(az)) > (MAX_SPEED if navigation else self.limits.speed_limit):
            return False
        # End an in-place maneuver with SDK STOP, never a coasting release.
        # Also zero the previous rotation before accepting a different maneuver.
        ending_in_place = self.turn_in_place and (mode == "release" or not turn_in_place)
        if ending_in_place or turn_in_place and mode == "release":
            if self.stop() is False:
                self.gate.disarm("actuator_failed")
                return False
            if mode == "release":
                return True
        self.turn_in_place = turn_in_place
        self._set_motion_target(lx, az)
        if self.t_lx == 0 and self.t_az == 0 and mode != "release":
            if not self._zero_goal():
                return False
        if mode == "pulse":
            self.curve_braking = [False, False]
        self.remote_decision_deadline = remote_decision_deadline
        self.remote_feedback_deadline = remote_feedback_deadline
        self.last_cmd_ts = self.gate.clock()
        # An explicit manual pulse owns its bounded duration. Continuous and
        # autonomous producers still require their original watchdog renewal.
        manual_pulse = self.gate.owner == "manual" and mode == "pulse" and remote_decision_deadline is None
        self.deadline = self.last_cmd_ts + (
            duration if panel_pulse or manual_pulse else min(duration, self.limits.watchdog_s)
        )
        return True

    def _operator_panel_pulse(self, panel_pulse):
        return bool(
            panel_pulse
            and self.gate.arming_mode == "operator"
            and self.gate.execution_context == "panel"
            and self.gate.owner == "manual"
        )

    def _set_motion_target(self, lx, az):
        crossing = self.o_lx * lx < 0 or self.o_az * az < 0
        continuing_pause = (
            self.reversing and self.reverse_until is not None and (self.t_lx * lx > 0 or self.t_az * az > 0)
        )
        self.reversing = crossing or continuing_pause
        if not continuing_pause:
            self.reverse_until = None
        self.t_lx, self.t_az = lx, az

    def _zero_goal(self):
        # A fresh zero goal is a pause within the current lease. STOP still
        # revokes the lease; deceleration never delays either zero output.
        for curve in self.curves:
            curve.reset()
        self.o_lx = self.o_az = 0.0
        self.reversing = False
        self.reverse_until = None
        self.stopped = True
        if not self.robot.move(lx=0.0, az=0.0):
            self.gate.disarm("actuator_failed")
            self.stop()
            return False
        return True

    @staticmethod
    def _approach(cur: float, tgt: float, rate: float, dt: float) -> float:
        return approach(cur, tgt, rate, dt)

    def expire_goal(self):
        # A bounded panel pulse ends movement, not the operator session.
        remote = self.remote_decision_deadline
        feedback = self.remote_feedback_deadline
        fresh_navigation = (
            remote is not None
            and self.gate.owner == "navigation"
            and self.gate.execution_context == "panel"
            and self.gate.clock() < remote
        )
        if self.gate.arming_mode != "operator" and not fresh_navigation:
            self.gate.disarm("motion_goal_timeout")
        if self.stop() is False:
            self.gate.disarm("actuator_failed")
        elif fresh_navigation:
            # Zero output between pulses; retain only the original decision TTL.
            self.remote_decision_deadline = remote
            self.remote_feedback_deadline = feedback

    def expire_remote_decision(self):
        now = self.gate.clock()
        feedback = self.remote_feedback_deadline
        if feedback is not None and now >= feedback:
            self.gate.disarm("decision_timeout")
            self.stop()
            return True
        if self.remote_decision_deadline is not None and now >= self.remote_decision_deadline:
            waiting = (
                feedback is not None
                and self.gate.owner == "navigation"
                and self.gate.execution_context == "panel"
                and self.gate.arming_mode in {"timed", "journey"}
            )
            if not waiting:
                self.gate.disarm("decision_timeout")
            if self.stop() is False:
                self.gate.disarm("actuator_failed")
            elif waiting:
                # Expired GO never moves motors. Retain only the independently
                # bounded feedback watchdog and the original operator ARM.
                self.remote_feedback_deadline = feedback
            return True
        return False

    def _tick_permitted(self, dt):
        if not self.gate.can_actuate() or (self.deadline and self.gate.clock() >= self.deadline):
            if self.deadline and self.gate.clock() >= self.deadline:
                self.expire_goal()
            if not self.stopped or self.deadline:
                self.stop()
            return False
        if not self.deadline:
            return False
        if not self.limits.valid or not finite(dt) or not 0 < dt <= self.limits.max_dt_s:
            if self.limits.valid:
                self.gate.cancel_motion("control_timing_invalid")
            else:
                self.gate.disarm("invalid_motion_limits")
            self.stop()
            return False
        return True

    def _ramp_targets(self):
        """Brake translation before in-place yaw and preserve zero-crossing reversal."""
        targets = [self.t_lx, self.t_az]
        if self.turn_in_place and self.o_lx != 0:
            # Finish translation before beginning the requested yaw.
            return [0.0, 0.0]
        if self.reversing:
            targets = [0.0, 0.0]
            if self.o_lx == 0 and self.o_az == 0:
                if self.reverse_until is None:
                    self.reverse_until = self.gate.clock() + self.limits.reversal_pause
                if self.gate.clock() >= self.reverse_until:
                    self.reversing = False
                    targets = [self.t_lx, self.t_az]
        return targets

    def _axis_output(self, axis, current, target, acceleration, deceleration, dt, remaining):
        # Reserve deceleration inside the original deadline, never extend TTL.
        # Remote navigation renews a continuous target with fresh bounded permits.
        # Pre-braking every short permit repeatedly restarts S curves near zero.
        # Expiry still bypasses ramps in expire_remote_decision/expire_goal.
        """Apply the configured curve without pre-braking continuously renewed navigation permits."""
        if getattr(self, "intent_mode", "pulse") == "pulse" and self.remote_decision_deadline is None:
            if self.limits.ramp_mode:
                if remaining <= abs(current) * curve_factor(self.limits.ramp_mode) / deceleration + dt:
                    self.curve_braking[axis] = True
                if self.curve_braking[axis]:
                    target = 0.0
            else:
                target = max(-deceleration * remaining, min(deceleration * remaining, target))
        else:
            self.curve_braking[axis] = False
        slowing = abs(target) < abs(current) or current * target < 0
        return self.curves[axis].step(
            current, target, deceleration if slowing else acceleration, dt, self.limits.ramp_mode
        )

    def tick(self, dt: float):
        if self.expire_remote_decision():
            return False
        if not self._tick_permitted(dt):
            return False
        remaining = max(0.0, self.deadline - self.gate.clock())
        targets = self._ramp_targets()
        outputs = []
        for axis, (current, target, acceleration, deceleration) in enumerate(
            (
                (self.o_lx, targets[0], self.limits.linear_rate, self.limits.linear_deceleration),
                (self.o_az, targets[1], self.limits.turn_rate, self.limits.turn_deceleration),
            )
        ):
            outputs.append(self._axis_output(axis, current, target, acceleration, deceleration, dt, remaining))
        self.o_lx, self.o_az = outputs
        # Every nonzero normalized output may quantize to a physical SDK step.
        self.stopped = self.o_lx == 0 and self.o_az == 0
        # A curved pulse can reach zero before its deadline. Finish it with
        # the same SDK STOP used by expiry, rather than leaving a live goal.
        if self.turn_in_place and self.stopped and self.curve_braking[1]:
            if self.stop() is False:
                self.gate.disarm("actuator_failed")
                return False
            return True
        # Repeat current output while a fresh bounded goal exists. No SDK timers.
        if not self.robot.move(lx=self.o_lx, az=self.o_az):
            self.gate.disarm("actuator_failed")
            self.stop()
            return False
        if getattr(self, "intent_mode", "pulse") == "release" and self.stopped:
            self.deadline = 0.0
        return True


def main():
    from apps.motion.executor import main as executor_main

    return executor_main()


if __name__ == "__main__":
    raise SystemExit(main())
