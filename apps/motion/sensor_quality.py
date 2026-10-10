"""Sole-owner measurement times and validity; no battery/tilt thresholds guessed."""

from __future__ import annotations

from apps.motion.dynamics import finite
from common.observations import CONTRACT_ID, CONTRACT_VERSION, UNITS, measurement, normalize_xgo_observation

MAX_SENSOR_AGE_S = 2.5
AXES = ("roll", "pitch", "yaw")
REQUIRED = AXES + ("battery",)


class SensorSamples:
    def __init__(self, clock, wall_clock, *, instance_id=None, simulated=False):
        self.clock, self.wall_clock = clock, wall_clock
        self.instance_id = instance_id
        self.simulated = bool(simulated)
        self.rows = {}

    def observe(self, name, value, *, measured_at=None, monotonic_at=None):
        measured_at = self.wall_clock() if measured_at is None else measured_at
        monotonic_at = self.clock() if monotonic_at is None else monotonic_at
        valid = finite(value) and (name != "battery" or 0 <= value <= 1)
        previous = self.rows.get(name)
        if (
            previous
            and finite(measured_at)
            and finite(previous["observed_at"])
            and measured_at < previous["observed_at"]
        ):
            valid = False
        valid = valid and finite(measured_at) and finite(monotonic_at)
        self.rows[name] = {
            "value": value if valid else None,
            "observed_at": measured_at if finite(measured_at) else None,
            "monotonic_at": monotonic_at if finite(monotonic_at) else None,
            "error": None if valid else "invalid_or_missing_measurement",
        }

    def quality(self):
        now, wall = self.clock(), self.wall_clock()
        rows = {}
        for name in REQUIRED:
            row = self.rows.get(name, {})
            ts, mono = row.get("observed_at"), row.get("monotonic_at")
            mono_age = now - mono if finite(mono) else None
            wall_age = wall - ts if finite(ts) else None
            age = max(mono_age, wall_age) if finite(mono_age) and finite(wall_age) else None
            fresh = age is not None and 0 <= age <= MAX_SENSOR_AGE_S and mono_age >= 0 and wall_age >= 0
            ready = fresh and row.get("value") is not None and not row.get("error")
            rows[name] = {
                "value": row.get("value") if ready else None,
                "observed_at": ts,
                "age_s": max(0.0, age) if finite(age) else None,
                "ready": bool(ready),
                "error": None if ready else row.get("error") or "measurement_stale_or_missing",
                "unit": UNITS[name],
                "source": "motion-executor",
                "instance_id": self.instance_id,
                "simulated": self.simulated,
                "max_age_s": MAX_SENSOR_AGE_S,
                "physical_validity": "unverified",
            }
        missing = [name for name, row in rows.items() if not row["ready"]]
        times = [row["observed_at"] for row in rows.values() if finite(row["observed_at"])]
        return {
            "ready": not missing,
            "error": "sensor_quality:" + ",".join(missing) if missing else None,
            "observed_at": min(times) if len(times) == len(REQUIRED) else None,
            "max_age_s": MAX_SENSOR_AGE_S,
            "sensors": rows,
            "battery_policy": "manual_characterization_required",
            "tilt_policy": "manual_characterization_required",
            "physical_safety": "unverified",
        }

    def payload(self, firmware=None):
        quality = self.quality()
        rows = quality["sensors"]
        axes = {name: rows[name]["value"] for name in AXES}
        imu_ok = all(rows[name]["ready"] for name in AXES)
        imu_times = [rows[name]["observed_at"] for name in AXES if finite(rows[name]["observed_at"])]
        return {
            "contract_id": CONTRACT_ID,
            "contract_version": CONTRACT_VERSION,
            "ts": self.wall_clock(),  # Publication time, never measurement time.
            "generated_at": self.wall_clock(),
            "source": "motion-executor",
            "instance_id": self.instance_id,
            "simulated": self.simulated,
            "observed_at": quality["observed_at"],
            "sensor_observed_at": {name: row["observed_at"] for name, row in rows.items()},
            "sensor_age_s": {name: row["age_s"] for name, row in rows.items()},
            "imu_observed_at": min(imu_times) if len(imu_times) == len(AXES) else None,
            "battery_observed_at": rows["battery"]["observed_at"],
            "imu": axes,
            "battery": rows["battery"]["value"],
            "fw": firmware,
            "src": "motion-executor",
            "uart_owner": "motion-executor",
            "imu_ok": imu_ok,
            "battery_ok": rows["battery"]["ready"],
            "sensor_quality": quality,
        }


def projected_samples(sensor, *, now):
    """Validate original per-channel timestamps again at the BUS consumer."""
    sensor = normalize_xgo_observation("motion.sensor.raw", sensor, now=now)
    values, quality = {}, {}
    for name in REQUIRED:
        row = sensor["sensor_quality"]["sensors"].get(name)
        row = row if isinstance(row, dict) else measurement(name, None, None, now=now)
        good = row.get("ready") is True
        values[name] = row.get("value") if good else None
        quality[name] = {**row, "ready": good, "observed_at": row.get("observed_at"), "age_s": row.get("age_s")}
    return values, quality
