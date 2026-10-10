#!/usr/bin/env python3
"""Compatibility sensor reader: sole-owner BUS projection, never a second UART."""

from __future__ import annotations

from apps.motion.sensor_reader import SensorBusAdapter


class XGOClientRO:
    def __init__(self, port="/dev/ttyAMA0", baud=115200, timeout=0.6, verbose=False, subscriber=None):
        self._adapter = SensorBusAdapter(subscriber=subscriber)
        self.verbose = verbose

    def close(self):
        self._adapter.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def read_battery(self):
        return self._adapter.battery()

    def read_firmware(self):
        return self._adapter.version()

    def _axis(self, name):
        imu = self._adapter.imu()
        return imu.get(name) if imu else None

    def read_roll(self):
        return self._axis("roll")

    def read_pitch(self):
        return self._axis("pitch")

    def read_yaw(self):
        return self._axis("yaw")

    def read_imu(self):
        imu = self._adapter.imu()
        return [imu[key] for key in ("roll", "pitch", "yaw")] if imu else None


if __name__ == "__main__":
    raise SystemExit("Use scripts/diag_motion-status.py to observe published telemetry.")
