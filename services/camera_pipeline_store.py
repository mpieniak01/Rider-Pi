"""Pi-owned camera profile and bounded request journal; never opens hardware."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from services.compute_config import _write

DEFAULT_PROFILE = {"analysis_location": "venom", "local_engine": "canny", "remote_transport": "snapshots"}
PROFILE_VALUES = {
    "analysis_location": {"local", "venom"},
    "local_engine": {"canny", "ssd", "tflite"},
    "remote_transport": {"snapshots", "mjpeg"},
}


def config_path():
    return Path(os.getenv("RIDER_CAMERA_PIPELINE_CONFIG", "data/camera_pipeline.json"))


def runtime_path():
    return Path(os.getenv("RIDER_CAMERA_PIPELINE_RUNTIME", "/run/rider-camera"))


def validate_profile(profile):
    if not isinstance(profile, dict) or set(profile) != set(PROFILE_VALUES):
        raise ValueError("camera_pipeline_invalid_profile")
    if any(not isinstance(profile[key], str) or profile[key] not in values for key, values in PROFILE_VALUES.items()):
        raise ValueError("camera_pipeline_invalid_profile")
    return dict(profile)


def snapshot():
    path = config_path()
    if not path.exists():
        return {"contract_version": 1, "revision": 1, "profile": dict(DEFAULT_PROFILE)}
    if path.stat().st_size > 16384:
        raise ValueError("camera_pipeline_config_invalid")
    data = json.loads(path.read_text())
    if (
        not isinstance(data, dict)
        or set(data) != {"contract_version", "revision", "profile"}
        or type(data["contract_version"]) is not int
        or data["contract_version"] != 1
        or type(data["revision"]) is not int
        or data["revision"] < 1
    ):
        raise ValueError("camera_pipeline_config_invalid")
    validate_profile(data["profile"])
    return data


def enabled():
    return config_path().is_file()


def native(profile=None):
    selected = snapshot()["profile"] if profile is None else profile
    return selected["analysis_location"] == "venom" and selected["remote_transport"] == "mjpeg"


def validate_request(data):
    if not isinstance(data, dict):
        raise ValueError("camera_pipeline_invalid_request")
    required = {"contract_version", "request_id", "expected_revision", "action"}
    if set(data) != required | ({"profile"} if data.get("action") == "configure" else set()):
        raise ValueError("camera_pipeline_invalid_request")
    if (
        type(data["contract_version"]) is not int
        or data["contract_version"] != 1
        or type(data["expected_revision"]) is not int
        or data["expected_revision"] < 1
        or not isinstance(data["request_id"], str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", data["request_id"])
        or not isinstance(data["action"], str)
        or data["action"] not in {"configure", "start", "stop"}
    ):
        raise ValueError("camera_pipeline_invalid_request")
    if data["action"] == "configure":
        validate_profile(data["profile"])
    return data


def write(data):
    _write(config_path(), data)
