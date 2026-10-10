"""Load recorded SDK step measurements; never infer physical units from UI speed."""

import json
import os
from pathlib import Path

from common.data_quality import finite_number


def load_calibration(path=None):
    path = path or os.getenv("ODOMETRY_CALIBRATION_PATH")
    if not path:
        return {}
    try:
        record = Path(path)
        if record.stat().st_size > 65536:
            return {}
        value = json.loads(record.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def calibration_status(record):
    if (
        not isinstance(record, dict)
        or type(record.get("schema_version")) is not int
        or record["schema_version"] != 1
        or record.get("manual_verified") is not True
    ):
        return "manual_calibration_required"
    if not isinstance(record.get("measurement_id"), str) or not record["measurement_id"].strip():
        return "measurement_id_required"
    conditions = record.get("conditions")
    if not isinstance(conditions, dict) or any(
        not conditions.get(key) for key in ("firmware", "surface", "load", "battery")
    ):
        return "measurement_conditions_required"
    if record.get("imu_yaw_sign") not in (-1, 1) or type(record.get("imu_yaw_sign")) is bool:
        return "imu_yaw_direction_unverified"
    for name in ("linear_m_s", "turn_rad_s"):
        table = record.get(name)
        if not isinstance(table, dict) or not table:
            return "sdk_step_measurements_required"
        for key, value in table.items():
            try:
                step = int(key)
            except (ValueError, TypeError):
                return "invalid_sdk_step_measurement"
            if str(step) != key or step == 0 or not finite_number(value) or value * step <= 0:
                return "invalid_sdk_step_measurement"
    return None


def measured_rate(record, table, step):
    if step == 0:
        return 0.0
    value = record.get(table, {}).get(str(step))
    return value if finite_number(value) else None
