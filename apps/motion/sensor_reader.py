"""BUS projection of sole-owner sensor reads. This process never opens UART."""

from __future__ import annotations

import time
from typing import Any

from apps.motion.sensor_quality import AXES, projected_samples
from common.observations import CONTRACT_ID, CONTRACT_VERSION, observation


def project_sensor_payload(sensor: dict | None, *, now: float | None = None) -> tuple[dict, dict]:
    now = time.time() if now is None else now
    sensor = sensor if isinstance(sensor, dict) else {}
    values, quality = projected_samples(sensor, now=now)
    axes = {key: values[key] for key in AXES}
    imu_ok = all(quality[key]["ready"] for key in AXES)
    imu_times = [quality[key]["observed_at"] for key in AXES if quality[key]["observed_at"] is not None]
    observed = min(imu_times) if len(imu_times) == len(AXES) else None
    base = {
        **observation(
            {key: quality[key] for key in AXES},
            source="motion-executor",
            firmware=sensor.get("fw"),
            instance_id=sensor.get("instance_id"),
            uart_owner="motion-executor",
            generated_at=sensor.get("generated_at", sensor.get("ts")),
        ),
        **axes,
        "ts": observed,
        "observed_at": observed,
        "yaw_src": "imu",
        "src": "motion-executor",
        "imu_ok": bool(imu_ok),
        "sensor_observed_at": {key: quality[key]["observed_at"] for key in AXES},
        "imu_observed_at": observed,
    }
    device = {
        **base,
        **observation(
            quality,
            source="motion-executor",
            firmware=sensor.get("fw"),
            instance_id=sensor.get("instance_id"),
            uart_owner="motion-executor",
            generated_at=sensor.get("generated_at", sensor.get("ts")),
        ),
        "battery": values["battery"],
        # Existing BUS alias always meant ratio. Unit is explicit; HTTP default
        # percent projection is made only by common.observations.legacy_xgo.
        "battery_pct": values["battery"],
        "battery_unit": "ratio",
        "units": {"battery_pct": "ratio", **dict.fromkeys(AXES, "sdk_raw")},
        "battery_observed_at": quality["battery"]["observed_at"],
        "battery_ok": quality["battery"]["ready"],
        "pose": {"x": axes["roll"], "y": axes["pitch"], "z": axes["yaw"]} if imu_ok else None,
        "pose_kind": "legacy_imu_projection",
        "contract_id": CONTRACT_ID,
        "contract_version": CONTRACT_VERSION,
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
