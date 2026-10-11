"""Hardware-free telemetry contract and explicit adapters for old BUS formats.

Observation times belong to measurements, never HTTP/BUS reception. The legacy
percent/wrapped projections are display adapters, not physical validation.
"""

from __future__ import annotations

import math
import time

CONTRACT_ID = "rider.telemetry"
CONTRACT_VERSION = 1
MAX_AGE_S = 2.5
AXES = ("roll", "pitch", "yaw")
SENSORS = AXES + ("battery",)
OPTIONAL_SENSORS = ("accel_x", "accel_y", "accel_z", "work_status")
ALL_SENSORS = SENSORS + OPTIONAL_SENSORS
UNITS = {
    **dict.fromkeys(AXES, "sdk_raw"),
    "battery": "ratio",
    **dict.fromkeys(OPTIONAL_SENSORS[:3], "m/s^2"),
    "work_status": "code",
}
PREFIXES = ("devices.xgo", "xgo", "motion.bridge.telemetry")


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def source_time(value):
    return value if finite(value) and value > 0 else None


def _rows(payload):
    quality = payload.get("sensor_quality")
    quality = quality if isinstance(quality, dict) else {}
    rows = quality.get("sensors", quality)
    return rows if isinstance(rows, dict) else {}


def _source(payload):
    return payload.get("source") or payload.get("src") or "unknown"


def _transport_error(payload):
    error = payload.get("error")
    # Safety can have a domain aggregate fault while individual source samples
    # are healthy. The aggregate is retained in sensor_quality, not transport.
    return None if isinstance(error, str) and error.startswith("sensor_quality:") else error


def measurement(name, value, observed_at, *, quality=None, source="unknown", now=None, unit=None, error=None):
    """Retain raw/source time; assessed_at dates only this age/quality assessment."""
    now = time.time() if now is None else now
    quality = quality if isinstance(quality, dict) else {}
    at = source_time(observed_at)
    age = now - at if at is not None and finite(now) else None
    unit = UNITS[name] if unit is None else unit
    valid = (
        finite(value)
        and (name != "battery" or 0 <= value <= 1)
        and (name != "work_status" or type(value) is int and value in {0, 1})
    )
    if unit != UNITS[name]:
        error = error or "measurement_unit_unknown"
        valid = False
    if not valid:
        value = None
        error = error or "invalid_or_missing_measurement"
    error = error or quality.get("error")
    if quality.get("offline") is True:
        error = error or "measurement_offline"
    if quality.get("simulated") is True:
        error = error or "measurement_simulated"
    if quality.get("stale") is True or quality.get("ready") is False:
        error = error or "measurement_not_ready"
    if not finite(age) or not 0 <= age <= MAX_AGE_S:
        error = error or "measurement_stale_or_missing"
    ready = valid and not error
    result = {
        "value": value,
        "unit": UNITS[name],
        "source": quality.get("source") or source,
        "observed_at": at,
        "assessed_at": source_time(now),
        "age_s": age if finite(age) else None,
        "ready": bool(ready),
        "stale": not finite(age) or not 0 <= age <= MAX_AGE_S or quality.get("stale") is True,
        "offline": quality.get("offline") is True,
        "error": error,
        "max_age_s": MAX_AGE_S,
        "physical_validity": "unverified",
        "physical_validation": "unverified",
    }
    for key in ("instance_id", "generation", "simulated"):
        if key in quality:
            result[key] = quality[key]
    return result


def _battery(value, unit):
    if unit == "percent":
        return value / 100 if finite(value) and 0 <= value <= 100 else None
    return value if unit == "ratio" else None


def normalize_xgo_observation(topic, payload, *, now=None):
    """Named legacy formats are accepted; ambiguous units never use heuristics."""
    if topic not in {"imu.data", "motion.sensor.raw", "motion.bridge.battery_pct"} and not any(
        topic == prefix or topic.startswith(prefix + ".") for prefix in PREFIXES
    ):
        return None
    data = dict(payload) if isinstance(payload, dict) else {}
    for prefix in PREFIXES + ("motion.bridge",):
        if topic.startswith(prefix + "."):
            suffix = topic[len(prefix) + 1 :]
            if suffix in SENSORS + ("battery_pct", "fw"):
                data[suffix] = data.get(suffix, data.get("value")) if isinstance(payload, dict) else payload
            break
    if isinstance(data.get("observation"), dict):
        data = data["observation"]
    canonical = (
        data.get("contract_id") == CONTRACT_ID
        and type(data.get("contract_version")) is int
        and data.get("contract_version") == CONTRACT_VERSION
    )
    if ("contract_id" in data or "contract_version" in data) and not canonical:
        return observation({}, source=_source(data), error="unsupported_telemetry_contract")
    source, rows = _source(data), _rows(data)
    times = data.get("sensor_observed_at")
    times = times if isinstance(times, dict) else {}
    imu = data.get("imu")
    imu = imu if isinstance(imu, dict) else {}
    normalized = {}
    for name in ALL_SENSORS:
        row = rows.get(name)
        row = row if isinstance(row, dict) else {}
        key = "battery_pct" if name == "battery" and "battery" not in data else name
        present = name in data or key in data or name in imu or (canonical and "value" in row)
        if not present:
            continue
        value = row.get("value") if canonical and "value" in row else data.get(key, imu.get(name))
        units = data.get("units")
        units = units if isinstance(units, dict) else {}
        unit = row.get("unit", "unknown") if canonical else row.get("unit", data.get(name + "_unit", units.get(name)))
        if unit is None:
            # These topic schemas, rather than numeric magnitudes, identify units.
            unit = "percent" if name == "battery" and topic.startswith(("motion.bridge.", "xgo")) else UNITS[name]
        if name == "battery":
            value = _battery(value, unit)
            unit = "ratio" if unit in {"percent", "ratio"} else unit
        time_key = "battery_observed_at" if name == "battery" else "imu_observed_at"
        at = (
            row["observed_at"]
            if "observed_at" in row
            else times[name]
            if name in times
            else data[time_key]
            if time_key in data
            else data["observed_at"]
            if "observed_at" in data
            else None
            if topic == "motion.sensor.raw"
            else data.get("ts")
        )
        flags = dict(row)
        # Aggregate IMU failure does not invalidate an explicitly healthy axis.
        if not row:
            flags.update(stale=data.get("stale") is True)
            if data.get("battery_ok" if name == "battery" else "imu_ok") is False:
                flags["ready"] = False
        if data.get("offline") is True:
            flags["offline"] = True
        for identity in ("instance_id", "generation", "simulated"):
            if identity in data or identity in row:
                flags[identity] = row.get(identity, data.get(identity))
        normalized[name] = measurement(
            name, value, at, quality=flags, source=source, now=now, unit=unit, error=_transport_error(data)
        )
    return observation(
        normalized,
        source=source,
        firmware=data.get("fw"),
        instance_id=data.get("instance_id"),
        uart_owner=data.get("uart_owner"),
        generated_at=data.get("generated_at", data.get("ts")),
        offline=data.get("offline") is True,
        error=_transport_error(data),
    )


def observation(
    rows,
    *,
    source="unknown",
    firmware=None,
    instance_id=None,
    uart_owner=None,
    generated_at=None,
    offline=False,
    error=None,
):
    """One domain payload shared by BUS and canonical HTTP projections.

    sensor_quality.sensors contains original measurements, with ratio battery
    and physically unverified sdk_raw axes. derived.yaw_display is a named
    display-only wrap of the raw yaw, retaining that measurement's source time
    and quality; it never replaces or validates the original SDK value.
    """
    rows = {name: dict(row) for name, row in rows.items() if name in ALL_SENSORS and isinstance(row, dict)}
    times = [rows.get(name, {}).get("observed_at") for name in SENSORS]
    observed = min(times) if times and all(source_time(at) is not None for at in times) else None
    partial = any(name not in rows or rows[name].get("ready") is not True for name in SENSORS)
    ready = not partial and not offline and not error
    yaw = rows.get("yaw")
    yaw_display = (
        {
            **yaw,
            "value": round((yaw["value"] + 180) % 360 - 180, 2) if finite(yaw.get("value")) else None,
            "unit": "legacy_wrapped_degrees",
            "display_only": True,
            "derivation": "legacy_wrap_180",
            "physical_validity": "unverified",
            "physical_validation": "unverified",
        }
        if yaw is not None
        else None
    )
    return {
        "contract_id": CONTRACT_ID,
        "contract_version": CONTRACT_VERSION,
        "source": source,
        "instance_id": instance_id,
        "observed_at": observed,
        "generated_at": source_time(generated_at),
        "fw": firmware,
        "uart_owner": uart_owner,
        "offline": bool(offline),
        # A missing axis is a channel fault, not an outage of a healthy battery.
        "stale": not rows or all(row.get("stale") is True for row in rows.values()),
        "error": error,
        "partial": partial or offline or bool(error),
        "derived": {"yaw_display": yaw_display},
        "sensor_quality": {
            "ready": ready,
            "max_age_s": MAX_AGE_S,
            "observed_at": observed,
            "sensors": rows,
            "error": None if ready else "sensor_quality_unavailable",
        },
        "physical_validity": "unverified",
        "physical_validation": "unverified",
    }


def refresh_observation(data, *, now=None):
    """Recompute age without replacing any measurement identity or timestamp."""
    if not isinstance(data, dict):
        return None
    rows = {
        name: measurement(
            name,
            row.get("value"),
            row.get("observed_at"),
            quality=row,
            source=data.get("source", "unknown"),
            now=now,
            unit=row.get("unit"),
        )
        for name, row in _rows(data).items()
        if name in ALL_SENSORS and isinstance(row, dict)
    }
    return observation(
        rows,
        source=data.get("source", "unknown"),
        firmware=data.get("fw"),
        instance_id=data.get("instance_id"),
        uart_owner=data.get("uart_owner"),
        generated_at=data.get("generated_at"),
        offline=data.get("offline") is True,
        error=data.get("error"),
    )


def legacy_xgo(data):
    """Explicit percent / wrapped display projection, never the canonical model."""
    data = data if isinstance(data, dict) else {}
    rows = _rows(data)
    values = {name: rows.get(name, {}).get("value") for name in SENSORS}
    yaw = values["yaw"]
    wrapped = round((yaw + 180) % 360 - 180, 2) if finite(yaw) else None
    imu_times = [rows.get(name, {}).get("observed_at") for name in AXES]
    imu_at = min(imu_times) if all(source_time(at) is not None for at in imu_times) else None
    return {
        "present": bool(rows) or data.get("fw") is not None,
        "roll": values["roll"],
        "pitch": values["pitch"],
        "yaw": wrapped,
        "yaw_raw": yaw,
        "battery_pct": values["battery"] * 100 if finite(values["battery"]) else None,
        "battery_unit": "percent",
        "yaw_unit": "legacy_wrapped_degrees",
        "yaw_raw_unit": "sdk_raw",
        "yaw_derivation": {"kind": "legacy_wrap_180", "display_only": True, "physical_validation": "unverified"},
        "pose": {"x": values["roll"], "y": values["pitch"], "z": yaw} if any(finite(values[n]) for n in AXES) else None,
        "pose_kind": "legacy_imu_projection",
        "fw": data.get("fw"),
        "source": data.get("source", "unknown"),
        "ts": data.get("observed_at"),
        "observed_at": data.get("observed_at"),
        "stale": data.get("stale") is True or data.get("offline") is True,
        "offline": data.get("offline") is True,
        "error": data.get("error"),
        "imu_ok": all(rows.get(name, {}).get("ready") is True for name in AXES),
        "battery_ok": rows.get("battery", {}).get("ready") is True,
        "acceleration": {
            axis: rows.get("accel_" + axis, {}).get("value") if rows.get("accel_" + axis, {}).get("ready") else None
            for axis in ("x", "y", "z")
        },
        "acceleration_unit": "m/s^2",
        "acceleration_includes_gravity": True,
        "work_status": rows.get("work_status", {}).get("value") if rows.get("work_status", {}).get("ready") else None,
        "sensor_quality": rows,
        "sensor_observed_at": {name: row.get("observed_at") for name, row in rows.items()},
        "imu_observed_at": imu_at,
        "battery_observed_at": rows.get("battery", {}).get("observed_at"),
        "uart_owner": data.get("uart_owner"),
        "physical_validation": "unverified",
        "observation": data,
    }


def canonical_telemetry_payload(payload):
    """HTTP negotiation uses the domain once, keeping default legacy bodies intact."""
    if not isinstance(payload, dict) or not isinstance(payload.get("devices"), dict):
        return payload
    xgo = payload["devices"].get("xgo")
    if not isinstance(xgo, dict) or not isinstance(xgo.get("observation"), dict):
        return payload
    return {**payload, "devices": {**payload["devices"], "xgo": xgo["observation"]}}
