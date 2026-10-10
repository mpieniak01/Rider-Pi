"""Shared motion controller. The only process entry point is the executor."""

from __future__ import annotations

import os

from apps.safety.estop import estop_triggered as estop_triggered, motion_enabled as motion_enabled, safe_speed
from apps.safety.gate import MAX_DURATION_S, MotionGate

WATCHDOG_MS = float(os.getenv("MOTION_WATCHDOG_MS", "500"))
LOOP_DT = 0.02
SPEED_LIMIT = min(1.0, max(0.0, float(os.getenv("MOTION_SPEED_LIMIT", "0.6"))))
RAMP_LX = float(os.getenv("MOTION_RAMP_LX", "1.0"))
RAMP_AZ = float(os.getenv("MOTION_RAMP_AZ", "2.0"))
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
        return True

    def set_height(self, height):
        return True

    def action(self, name):
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

    def read_sensor(self, name):
        if name == "battery":
            return self._ada.battery()
        if name == "firmware":
            return self._ada.firmware()
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


def _make_adapter(gate: MotionGate | None = None):
    if os.getenv("RIDER_SIMULATOR") == "1" or os.getenv("RIDER_TEST_ISOLATED") == "1":
        return _SimAdapter()
    # Missing hardware never becomes a successful simulation in production.
    return _RealAdapter(gate or MotionGate())


class MotionController:
    def __init__(self, robot, gate: MotionGate | None = None):
        self.robot = robot
        self.gate = gate or MotionGate()
        self.last_cmd_ts = 0.0
        self.deadline = 0.0
        self.stopped = True
        self.t_lx = self.t_az = self.o_lx = self.o_az = 0.0

    def _stop_immediate(self):
        self.t_lx = self.t_az = self.o_lx = self.o_az = 0.0
        self.deadline = self.last_cmd_ts = 0.0
        self.stopped = True
        return self.robot.stop()

    stop = _stop_immediate

    def drive(self, lx: float, az: float, duration: float = MAX_DURATION_S):
        if not self.gate.can_actuate():
            self.stop()
            return False
        self.t_lx = safe_speed(lx, SPEED_LIMIT)
        self.t_az = safe_speed(az, SPEED_LIMIT)
        self.last_cmd_ts = self.gate.clock()
        self.deadline = self.last_cmd_ts + min(duration, WATCHDOG_MS / 1000.0)
        return True

    @staticmethod
    def _approach(cur: float, tgt: float, rate: float, dt: float) -> float:
        delta = max(-rate * dt, min(rate * dt, tgt - cur))
        return cur + delta

    def tick(self, dt: float):
        if not self.gate.can_actuate() or (self.deadline and self.gate.clock() >= self.deadline):
            if not self.stopped or self.deadline:
                self.stop()
            return False
        if not self.deadline:
            return False
        dt = max(0.0, min(0.1, dt))
        self.o_lx = self._approach(self.o_lx, self.t_lx, RAMP_LX, dt)
        self.o_az = self._approach(self.o_az, self.t_az, RAMP_AZ, dt)
        self.stopped = abs(self.o_lx) <= EPS and abs(self.o_az) <= EPS
        # Repeat current output while a fresh bounded goal exists. No SDK timers.
        if not self.robot.move(lx=self.o_lx, az=self.o_az):
            self.gate.disarm("actuator_failed")
            self.stop()
            return False
        return True


def main():
    from apps.motion.executor import main as executor_main

    return executor_main()


if __name__ == "__main__":
    raise SystemExit(main())
