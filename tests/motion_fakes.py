"""Shared mock motion fixtures; every adapter and SDK call stays in memory."""

from __future__ import annotations

import pytest

from apps.motion.executor import MotionExecutor
from apps.safety import estop
from apps.safety.gate import MotionGate


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeAdapter:
    simulated = True
    error = None

    def __init__(self):
        self.calls = []

    def ok(self):
        return True

    def move(self, lx, az):
        self.calls.append(("move", lx, az))
        return True

    def stop(self):
        self.calls.append(("stop",))
        return True

    def enable_balance(self, enabled):
        self.calls.append(("balance", enabled))
        return True

    def set_height(self, height):
        self.calls.append(("height", height))
        return True

    def action(self, name):
        self.calls.append(("action", name))
        return True

    def get_imu(self):
        return {"roll": 1.0, "pitch": 2.0, "yaw": 3.0}

    def battery(self):
        return 0.8

    def firmware(self):
        return "R-fake"

    def close(self):
        self.calls.append(("close",))


@pytest.fixture
def executor(monkeypatch, tmp_path):
    monkeypatch.setenv("RIDER_TEST_ISOLATED", "1")
    monkeypatch.setenv("RIDER_MANUAL_SETTINGS_PATH", str(tmp_path / "manual-controls.json"))
    monkeypatch.delenv("MOTION_ENABLE", raising=False)
    monkeypatch.delenv("ESTOP", raising=False)
    monkeypatch.setenv("ESTOP_GPIO", "-1")
    monkeypatch.setattr(estop, "ESTOP_FLAG", tmp_path / "estop.on")
    clock = Clock()
    gate = MotionGate(clock=clock, wall_clock=clock, blocked=lambda: estop.ESTOP_FLAG.exists())
    adapter = FakeAdapter()
    instance = MotionExecutor(gate=gate, adapter=adapter, status_writer=lambda _state: None)
    instance.poll_sensors()  # Fake adapter only; supplies known finite measurements.
    instance.last_sensors = 0.0  # Tests may independently exercise the fake read schedule.
    return instance, clock


def command(executor, action="move", **kwargs):
    result = {
        "action": action,
        "request_id": "isolated-request",
        "source": "manual",
        "generation": executor.gate.generation,
        "seq": executor.gate.last_seq + 1,
        "ts": executor.gate.wall_clock(),
        "ttl_ms": 250,
        "vx": 0.1,
        "yaw": 0.0,
        "duration": 0.2,
    }
    from apps.motion.manual_settings import read

    result["settings_revision"] = read()["revision"]
    result.update(kwargs)
    return result


def arm(executor, **kwargs):
    return executor.apply(
        command(
            executor,
            "arm",
            operator_consent=True,
            operator_plan="Mock-only drive test",
            owner="manual",
            lease_s=10.0,
            **kwargs,
        )
    )


class FakeSDK:
    constructed = []

    def __init__(self, port, version):
        self.events = []
        self.ser = self
        self.reset()
        self._XGO__send("IMU")  # even unexpected constructor actuator writes blocked
        self.events.append(("read_firmware",))
        type(self).constructed.append(self)

    def reset(self):
        self.events.append(("reset",))
        self._XGO__send("ACTION")

    def _XGO__send(self, key, index=1, len=1):
        self.events.append(("write", key))

    def _XGO__unpack(self, timeout=1):
        return True

    def _XGO__read(self, addr, read_len=1):
        self.rx_ADDR = addr
        self.rx_LEN = read_len + 8
        self.rx_COUNT = read_len - 1
        self.rx_data = bytearray(read_len)

    def stop(self):
        self._XGO__send("VX")
        self._XGO__send("VYAW")

    def rider_move_x(self, step, runtime=0):
        self._XGO__send("VX")

    def turnleft(self, step):
        self._XGO__send("VYAW")

    def rider_read_battery(self):
        return 80

    def rider_read_roll(self):
        return 1

    def rider_read_pitch(self):
        return 2

    def rider_read_yaw(self):
        return 3

    def close(self):
        self.events.append(("closed",))
