"""One persisted executor selection on Pi. Heartbeats never modify routing."""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import re
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from common.compute_url import validate_compute_url

TASKS = ("text.respond", "audio.transcribe", "audio.synthesize", "vision.describe", "conversation.respond")
ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def config_path():
    return Path(os.getenv("RIDER_COMPUTE_CONFIG", "data/compute_config.json"))


def status_path():
    return Path(os.getenv("RIDER_COMPUTE_STATUS", "data/compute_status.json"))


@contextmanager
def _lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".compute-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _validate(data):
    if (
        not isinstance(data, dict)
        or data.get("protocol_version") != 1
        or type(data.get("revision")) is not int
        or data["revision"] < 0
        or not isinstance(data.get("device_id"), str)
        or not ID.fullmatch(data["device_id"])
        or not isinstance(data.get("executors"), dict)
        or len(data["executors"]) > 8
    ):
        raise ValueError("compute_configuration_invalid")
    for name, row in data["executors"].items():
        if not isinstance(name, str) or not ID.fullmatch(name) or not isinstance(row, dict):
            raise ValueError("compute_configuration_invalid")
        try:
            validate_compute_url(
                row.get("url", ""),
                allow_api_path=True,
                transport_profile=row.get("transport_profile", "secure"),
                expected_peer_id=row.get("expected_peer_id"),
            )
        except ValueError as exc:
            raise ValueError("compute_configuration_invalid") from exc
        if (
            not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", row.get("token_env", ""))
            or not isinstance(row.get("tasks"), list)
            or not row["tasks"]
            or set(row["tasks"]) - set(TASKS)
        ):
            raise ValueError("compute_configuration_invalid")
    chosen = data.get("selected_executor")
    if chosen is not None and chosen not in data["executors"]:
        raise ValueError("compute_configuration_invalid")
    return data


def _read():
    path = config_path()
    if not path.is_file():
        return {
            "protocol_version": 1,
            "revision": 0,
            "device_id": "unconfigured",
            "selected_executor": None,
            "executors": {},
        }
    if path.stat().st_size > 16384:
        raise ValueError("compute_configuration_invalid")
    try:
        return _validate(json.loads(path.read_text()))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("compute_configuration_invalid") from exc


def snapshot():
    data = _read()
    return {
        "protocol_version": 1,
        "revision": data["revision"],
        "device_id": data["device_id"],
        "selected_executor": data["selected_executor"],
        "persisted": config_path().is_file(),
        "executors": [
            {
                "id": name,
                "tasks": row["tasks"],
                "credential_configured": bool(os.getenv(row["token_env"])),
                "transport_profile": row.get("transport_profile", "secure"),
                "identity_pinned": bool(row.get("expected_peer_id")),
            }
            for name, row in data["executors"].items()
        ],
    }


def selected_executor():
    data = _read()
    selected = data["selected_executor"]
    if selected is None:
        return None
    row = data["executors"][selected]
    token = os.getenv(row["token_env"], "")
    if not token:
        raise ValueError("compute_credentials_unavailable")
    return {
        "id": selected,
        "url": row["url"].rstrip("/"),
        "token": token,
        "device_id": data["device_id"],
        "tasks": row["tasks"],
        "revision": data["revision"],
        "transport_profile": row.get("transport_profile", "secure"),
        "expected_peer_id": row.get("expected_peer_id"),
    }


def select(executor_id, revision):
    """Optimistic transaction; no service, model, media or actuator side effects."""
    if type(revision) is not int or executor_id is not None and not isinstance(executor_id, str):
        raise ValueError("compute_configuration_invalid")
    with _selection_lock(), _lock(config_path()):
        data = _read()
        if revision != data["revision"]:
            raise ValueError("compute_configuration_conflict")
        if executor_id is not None and executor_id not in data["executors"]:
            raise ValueError("compute_executor_unknown")
        if data["selected_executor"] != executor_id:
            _require_idle_goals()
            data["selected_executor"] = executor_id
            data["revision"] += 1
        _write(config_path(), data)
    return snapshot()


def _require_idle_goals():
    path = Path(os.getenv("FEATURE_STATE_PATH", "/run/rider-motion/feature_state.json"))
    if not path.is_file():
        return
    try:
        if path.stat().st_size > 256 * 1024:
            raise ValueError("oversized")
        requested = json.loads(path.read_text()).get("requested", [])
        if not isinstance(requested, list):
            raise ValueError("invalid")
    except (ValueError, OSError) as exc:
        raise ValueError("compute_goal_state_unavailable") from exc
    if set(requested) & {
        "s5_voice",
        "s7_obstacle_module",
        "s10_ai_providers",
        "s12_venom_vision",
        "s13_venom_voice",
        "s14_venom_navigation",
        "s15_venom_perception",
    }:
        raise ValueError("compute_stop_goals_first")


@contextmanager
def _selection_lock():
    from common.runtime_lock import exclusive

    path = Path(os.getenv("FEATURE_STATE_PATH", "/run/rider-motion/feature_state.json"))
    with exclusive(path.with_suffix(".lock")):
        yield


def configure(
    url,
    device_id,
    executor_id="venom",
    token_env="RIDER_COMPUTE_TOKEN",
    *,
    transport_profile="secure",
    expected_peer_id=None,
):
    """Emergency CLI shares this domain; credentials remain in the service env."""
    if not isinstance(url, str):
        raise ValueError("compute_configuration_invalid")
    with _selection_lock(), _lock(config_path()):
        _require_idle_goals()
        data = _read()
        data.update(device_id=device_id, revision=data["revision"] + 1)
        data["executors"][executor_id] = {
            "url": url.rstrip("/"),
            "token_env": token_env,
            "tasks": list(TASKS),
            "transport_profile": transport_profile,
            "expected_peer_id": expected_peer_id,
        }
        _write(config_path(), _validate(data))
    return snapshot()


def record_status(domain, observation, *, revision):
    if domain not in {"vision", "voice", "cli", "panel"} or not isinstance(observation, dict):
        raise ValueError("compute_status_invalid")
    if revision != _read()["revision"]:
        return False
    # A fixed projection prevents tokens, addresses and binary payloads entering
    # diagnostics. Model identifiers and bounded result text are intentional.
    allowed = {
        "state",
        "error",
        "observed_at",
        "selected_executor",
        "revision",
        "job_id",
        "input_id",
        "captured_at",
        "task",
        "runtime",
        "quality",
        "metrics",
        "data",
        "capabilities",
        "response_task",
        "executor_id",
        "executor_session",
        "client_id",
        "session_id",
        "device_id",
        "device_session",
        "transport_online",
        "transport",
    }
    row = {key: value for key, value in observation.items() if key in allowed}
    row.update(revision=revision, received_at=time.time())
    if isinstance(row.get("transport"), dict):
        row["transport"] = {
            key: value
            for key, value in row["transport"].items()
            if key in {"state", "error", "generation", "retry_after_s"}
        }
    else:
        row.pop("transport", None)
    if isinstance(row.get("data"), dict):
        row["data"] = {
            key: value[:4096] if isinstance(value, str) else value
            for key, value in row["data"].items()
            if key in {"text", "sample_rate", "language"}
        }
    if len(json.dumps(row, allow_nan=False).encode()) > 16384:
        raise ValueError("compute_status_invalid")
    with _lock(status_path()):
        try:
            data = json.loads(status_path().read_text()) if status_path().is_file() else {}
        except (ValueError, OSError):
            data = {}
        data[domain] = row
        _write(status_path(), data)
    return True


def observed_status():
    config = snapshot()
    try:
        path = status_path()
        data = json.loads(path.read_text()) if path.is_file() and path.stat().st_size <= 65536 else {}
    except (ValueError, OSError):
        data = {}
    now = time.time()
    domains = {}
    for domain in ("vision", "voice", "cli", "panel"):
        row = data.get(domain, {}) if isinstance(data, dict) else {}
        row = row if isinstance(row, dict) else {}
        at = row.get("received_at")
        age = now - at if type(at) in {int, float} and math.isfinite(at) else None
        stale = age is None or not -0.1 <= age <= 12 or row.get("revision") != config["revision"]
        domains[domain] = {
            **row,
            "stale": stale,
            "age_s": age,
            "state": "unknown" if stale else row.get("state", "unknown"),
        }
    return {
        "protocol_version": 1,
        "selected_executor": config["selected_executor"],
        "revision": config["revision"],
        "domains": domains,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--executor-id", default="venom")
    parser.add_argument("--token-env", default="RIDER_COMPUTE_TOKEN")
    parser.add_argument("--transport-profile", choices=("secure", "trusted_lan"), default="secure")
    parser.add_argument("--expected-peer-id")
    args = parser.parse_args()
    print(
        json.dumps(
            configure(
                args.url,
                args.device_id,
                args.executor_id,
                args.token_env,
                transport_profile=args.transport_profile,
                expected_peer_id=args.expected_peer_id,
            )
        )
    )


if __name__ == "__main__":
    main()
