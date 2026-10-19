"""Pure bounded calibration content validation, independent of storage and hardware."""

import json

from apps.odometry.calibration import calibration_status
from common.data_quality import finite_number

MAX_BYTES = 65536
MAX_MEASUREMENTS = 128


def _text(value, name, *, limit=4096, required=False):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value or required and not value.strip():
        raise ValueError(name)
    return value


def _bounded(value, depth=0):
    if depth > 8:
        raise ValueError("profile_too_deep")
    if value is None or type(value) is bool:
        return value
    if isinstance(value, str):
        return _text(value, "profile_string_invalid")
    if type(value) in (int, float):
        if not finite_number(value):
            raise ValueError("profile_number_invalid")
        return value
    if isinstance(value, list) and len(value) <= MAX_MEASUREMENTS:
        return [_bounded(item, depth + 1) for item in value]
    if isinstance(value, dict) and len(value) <= MAX_MEASUREMENTS:
        return {
            _text(key, "profile_key_invalid", limit=128, required=True): _bounded(item, depth + 1)
            for key, item in value.items()
        }
    raise ValueError("profile_value_invalid")


def _encode(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValueError("profile_oversized")
    return raw


def _fields(value, expected, code):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(code)


def _validate_interaction(value):
    if "interaction" in value:
        interaction = value["interaction"]
        _fields(interaction, ("linear_speed", "turn_speed", "pulse_duration"), "profile_interaction_fields")
        for field in ("linear_speed", "turn_speed", "pulse_duration"):
            number = interaction[field]
            upper = 0.25 if field == "pulse_duration" else 1.0
            lower = 0.01 if field == "pulse_duration" else 0.0
            if not finite_number(number) or not lower <= number <= upper:
                raise ValueError("profile_interaction_" + field)


def _validate_motion(motion):
    _fields(motion, ("speed_limit", "linear_rate", "turn_rate"), "profile_motion_fields")
    for field, ceiling in (("speed_limit", 1), ("linear_rate", 100), ("turn_rate", 100)):
        if not finite_number(motion[field]) or not 0 < motion[field] <= ceiling:
            raise ValueError("profile_motion_" + field)
        motion[field] = float(motion[field])


def _validate_sdk_table(table, ceiling):
    if not isinstance(table, dict) or len(table) > 2 * ceiling:
        raise ValueError("profile_sdk_table")
    for key, item in table.items():
        try:
            step = int(key)
        except (TypeError, ValueError):
            raise ValueError("profile_sdk_step") from None
        minimum = 1
        if str(step) != key or not minimum <= abs(step) <= ceiling:
            raise ValueError("profile_sdk_step")
        if not finite_number(item) or item * step <= 0:
            raise ValueError("profile_sdk_rate")


def _validate_odometry(record, provenance):
    _fields(
        record,
        (
            "schema_version",
            "manual_verified",
            "measurement_id",
            "conditions",
            "imu_yaw_sign",
            "linear_m_s",
            "turn_rad_s",
            "observations",
        ),
        "profile_odometry_fields",
    )
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise ValueError("profile_odometry_schema")
    if type(record["manual_verified"]) is not bool:
        raise ValueError("profile_odometry_verification")
    if provenance["kind"] != "manual":
        record["manual_verified"] = False
    _text(record["measurement_id"], "profile_measurement_id", limit=128)
    conditions = record["conditions"]
    if not isinstance(conditions, dict) or not {"firmware", "surface", "load", "battery"} <= set(conditions):
        raise ValueError("profile_conditions")
    for item in conditions.values():
        _text(item, "profile_condition", limit=1024)
    if record["imu_yaw_sign"] is not None and (
        type(record["imu_yaw_sign"]) is not int or record["imu_yaw_sign"] not in (-1, 1)
    ):
        raise ValueError("profile_imu_yaw_sign")
    for field, ceiling in (("linear_m_s", 127), ("turn_rad_s", 180)):
        _validate_sdk_table(record[field], ceiling)
    if not isinstance(record["observations"], dict):
        raise ValueError("profile_observations")
    return conditions


def _validate_measurement_numbers(row):
    for field in ("duration_s", "distance_m", "angle_rad"):
        number = row.get(field)
        if number is not None and (not finite_number(number) or field == "duration_s" and number <= 0):
            raise ValueError("profile_measurement_" + field)


def _validate_measurement(row):
    _validate_measurement_numbers(row)
    if "phase" in row and row["phase"] not in ("acceleration", "steady", "deceleration", "complete", "unknown"):
        raise ValueError("profile_measurement_phase")
    for field in ("status", "outcome"):
        if field in row and row[field] not in ("passed", "failed", "aborted", "unknown"):
            raise ValueError("profile_measurement_outcome")
    if row.get("sdk_step") is not None:
        step = row["sdk_step"]
        minimum, maximum = (1, 180) if row.get("kind") == "turn" else (1, 127)
        if type(step) is not int or not minimum <= abs(step) <= maximum:
            raise ValueError("profile_measurement_sdk_step")


def _validate_measurements(measurements):
    if not isinstance(measurements, list) or any(not isinstance(row, dict) for row in measurements):
        raise ValueError("profile_measurements")
    for row in measurements:
        _validate_measurement(row)


def _validate_manual_evidence(value, record, provenance, conditions):
    if record["manual_verified"]:
        error = calibration_status(record, require_mapping=False)
        if error:
            raise ValueError(error)
        if not conditions.get("operator", "").strip() or not conditions.get("date", "").strip():
            raise ValueError("profile_operator_and_date_required")
        if not provenance["notes"].strip() or not value["measurements"]:
            raise ValueError("profile_manual_evidence_required")
        if not any(
            row.get("measurement_id") == record["measurement_id"]
            and isinstance(row.get("notes"), str)
            and row["notes"].strip()
            for row in value["measurements"]
        ):
            raise ValueError("profile_matching_measurement_required")


def validate_profile(profile):
    """Return canonical content. Historical/draft records cannot assert verification."""
    value = _bounded(profile)
    required = {"schema_version", "name", "provenance", "motion", "odometry", "measurements"}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - {"interaction"}:
        raise ValueError("profile_schema")
    _validate_interaction(value)
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("profile_schema_version")
    value["name"] = _text(value["name"], "profile_name", limit=80, required=True).strip()
    provenance = value["provenance"]
    _fields(provenance, ("kind", "notes"), "profile_provenance")
    if provenance["kind"] not in ("draft", "historical", "manual"):
        raise ValueError("profile_provenance_kind")
    _text(provenance["notes"], "profile_provenance_notes")
    _validate_motion(value["motion"])
    record = value["odometry"]
    conditions = _validate_odometry(record, provenance)
    _validate_measurements(value["measurements"])
    _validate_manual_evidence(value, record, provenance, conditions)
    _encode(value)
    return value
