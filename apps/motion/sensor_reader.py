"""BUS projection of sole-owner sensor reads. This process never opens UART."""

from __future__ import annotations

import time
from typing import Any

MAX_SENSOR_AGE_S = 2.5


def project_sensor_payload(sensor: dict | None, *, now: float | None = None) -> tuple[dict, dict]:
    now = time.time() if now is None else now
    sensor = sensor or {}
    observed = sensor.get("observed_at", sensor.get("ts"))
    try:
        age = now - float(observed)
        fresh = 0 <= age <= MAX_SENSOR_AGE_S
    except (TypeError, ValueError):
        fresh = False
    imu = sensor.get("imu") if fresh else None
    imu = imu if isinstance(imu, dict) else {}
    axes = {key: imu.get(key) for key in ("roll", "pitch", "yaw")}
    imu_ok = fresh and all(value is not None for value in axes.values())
    base = {
        **axes,
        "ts": now,
        "observed_at": observed,
        "yaw_src": "imu",
        "src": "motion-executor",
        "uart_owner": "motion-executor",
        "stale": not fresh,
        "imu_ok": bool(imu_ok),
    }
    device = {
        **base,
        "battery_pct": sensor.get("battery") if fresh else None,
        "fw": sensor.get("fw") if fresh else None,
        "pose": {"x": axes["roll"], "y": axes["pitch"], "z": axes["yaw"]} if imu_ok else None,
    }
    return base, device


class SensorBusAdapter:
    """Compatibility reader for consumers that formerly constructed an SDK."""

    def __init__(self, subscriber=None):
        if subscriber is None:
            from common.bus import BusSub

            subscriber = BusSub(["motion.sensor.raw"])
        self.subscriber = subscriber
        self.sensor = None

    def refresh(self, timeout_ms=0):
        topic, payload = self.subscriber.recv(timeout_ms=timeout_ms)
        if topic == "motion.sensor.raw" and isinstance(payload, dict):
            self.sensor = payload

    def imu(self):
        self.refresh()
        imu, _ = project_sensor_payload(self.sensor)
        return {key: imu[key] for key in ("roll", "pitch", "yaw")} if imu["imu_ok"] else None

    def battery(self):
        self.refresh()
        _, device = project_sensor_payload(self.sensor)
        return device["battery_pct"]

    def version(self):
        _, device = project_sensor_payload(self.sensor)
        return device["fw"]

    def close(self):
        self.subscriber.close()


def make_adapter():
    return SensorBusAdapter()


def read_imu(adapter) -> tuple[float | None, float | None, float | None]:
    data = adapter.imu()
    if not isinstance(data, dict):
        return None, None, None
    return data.get("roll"), data.get("pitch"), data.get("yaw")


def read_battery(adapter) -> float | None:
    return adapter.battery()


def read_fw(adapter) -> Any:
    return adapter.version()


def main() -> int:
    from common import bus

    adapter = make_adapter()
    pub = bus.BusPub()
    try:
        while True:
            adapter.refresh(timeout_ms=1000)
            imu, device = project_sensor_payload(adapter.sensor)
            pub.publish(bus.TOPIC_IMU_DATA, imu, add_ts=False)
            pub.publish("devices.xgo", device, add_ts=False)
    except KeyboardInterrupt:
        return 0
    finally:
        adapter.close()
        pub.close()


if __name__ == "__main__":
    raise SystemExit(main())
