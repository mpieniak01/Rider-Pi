#!/usr/bin/env python3
"""
apps.motion.sensor_reader

Odczyt IMU/baterii z XGO i publikacja na busie:
- imu.data: roll, pitch, yaw, ts, src
- devices.xgo: battery_pct, fw, yaw, yaw_src, ts

Nie wykonuje żadnych komend ruchu.
"""

from __future__ import annotations

import os
import time
from typing import Any

from common import bus

try:
    from drivers.xgo import XgoAdapter
except Exception:
    XgoAdapter = None  # type: ignore

IMU_HZ = float(os.getenv("SENSOR_IMU_HZ", os.getenv("MOTION_IMU_HZ", "10.0")))
POLL_INTERVAL = 1.0 / max(0.1, IMU_HZ)


class SimAdapter:
    def imu(self) -> dict | None:
        return None

    def battery(self) -> float | None:
        return None

    def version(self) -> Any:
        return None


def make_adapter():
    if XgoAdapter is None:
        return SimAdapter()
    try:
        return XgoAdapter()
    except Exception as exc:  # pragma: no cover - zależne od HW
        print(f"[sensor_reader] XgoAdapter unavailable: {exc}", flush=True)
        return SimAdapter()


def read_imu(adapter) -> tuple[float | None, float | None, float | None]:
    try:
        data = adapter.imu()
        if isinstance(data, dict):
            return (
                float(data.get("roll")) if data.get("roll") is not None else None,
                float(data.get("pitch")) if data.get("pitch") is not None else None,
                float(data.get("yaw")) if data.get("yaw") is not None else None,
            )
    except Exception as exc:
        print(f"[sensor_reader] read_imu exception: {exc}", flush=True)
    return None, None, None


def read_battery(adapter) -> float | None:
    for name in ("battery", "get_battery", "read_battery"):
        fn = getattr(adapter, name, None)
        if callable(fn):
            try:
                return float(fn())
            except Exception:
                continue
    return None


def read_fw(adapter) -> Any:
    for name in ("version", "read_firmware"):
        fn = getattr(adapter, name, None)
        if callable(fn):
            try:
                return fn()
            except Exception:
                continue
    return None


def main() -> int:
    adapter = make_adapter()
    pub = bus.BusPub()
    last_telem = 0.0
    while True:
        roll, pitch, yaw = read_imu(adapter)
        ts = time.time()
        payload = {"roll": roll, "pitch": pitch, "yaw": yaw, "yaw_src": "imu", "ts": ts}
        pub.publish(bus.TOPIC_IMU_DATA, payload, add_ts=False)

        batt = read_battery(adapter)
        fw = read_fw(adapter)
        pose_axes = None
        if any(v is not None for v in (roll, pitch, yaw)):
            pose_axes = {"x": roll, "y": pitch, "z": yaw}

        dev_payload = {
            "battery_pct": batt,
            "fw": fw,
            "roll": roll,
            "pitch": pitch,
            "yaw": yaw,
            "yaw_src": "imu",
            "pose": pose_axes,
            "ts": ts,
            "imu_ok": roll is not None and pitch is not None and yaw is not None,
        }
        pub.publish("devices.xgo", dev_payload, add_ts=False)

        if ts - last_telem >= 5.0:
            print(f"[sensor_reader] imu: r={roll} p={pitch} y={yaw} batt={batt}", flush=True)
            last_telem = ts
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    import sys

    sys.exit(main())
