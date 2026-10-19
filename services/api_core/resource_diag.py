#!/usr/bin/env python3
"""Read-only exact device ownership; recovery is an explicit operator action."""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BASE_DIR = str(Path(__file__).resolve().parents[2])


@dataclass
class ProcessInfo:
    pid: int
    command: str
    user: str
    paths: list[str]


ALSA_PREFLIGHT = os.path.join(BASE_DIR, "config", "alsa", "preflight.sh")
CAMERA_FREE = os.path.join(BASE_DIR, "scripts", "sys_camera-free.sh")


def _default_capture_dev() -> str:
    return os.getenv("RESOURCE_MIC_DEVICE", "wm8960_in")


def _default_playback_dev() -> str:
    return os.getenv("RESOURCE_SPK_DEVICE", "wm8960_out")


def _existing_paths(patterns: Iterable[str]) -> list[str]:
    paths: list[str] = []
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches:
            paths.extend(matches)
    return sorted(set(paths))


def _run_lsof(paths: list[str]) -> list[ProcessInfo]:
    if not paths:
        return []
    # A user-only /proc scan can silently miss root-owned descriptors. Request
    # an existing noninteractive sudo read; unavailable privilege is unknown.
    prefix = [] if os.geteuid() == 0 else ["sudo", "-n"]
    cmd = [*prefix, "lsof", "-FpcuLn0", "--", *paths]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError:
        raise RuntimeError("lsof not found on PATH") from None

    # With several paths rc=1 can mean only some are open; complete owners
    # from the remaining paths still prove that this resource is occupied.
    if proc.returncode not in (0, 1) or proc.stderr.strip():
        msg = proc.stderr.strip() or proc.stdout.strip() or "unknown error"
        raise RuntimeError(f"lsof failed (rc={proc.returncode}): {msg}")
    if proc.returncode == 0 and not proc.stdout.strip():
        raise RuntimeError("lsof returned inconsistent ownership data")
    if len(paths) == 1 and proc.returncode == 1 and proc.stdout.strip():
        raise RuntimeError("single-device lsof returned inconsistent ownership data")

    return _parse_lsof(proc.stdout)


def _lsof_owner_pid(value):
    try:
        pid = int(value)
    except ValueError:
        raise RuntimeError("lsof returned malformed owner PID") from None
    if pid <= 1:
        raise RuntimeError("lsof returned invalid owner PID")
    return pid


def _lsof_detail(current, field, value, current_paths):
    if field == "c":
        current.command = value
    elif field == "L":
        current.user = value
    elif field == "n":
        if not value.strip():
            raise RuntimeError("lsof returned empty owner path")
        current_paths.append(value)


def _parse_lsof(output):
    entries: list[ProcessInfo] = []
    current: ProcessInfo | None = None
    current_paths: list[str] = []
    for token in output.split("\0"):
        token = token.lstrip("\n")
        if not token:
            continue
        field = token[0]
        value = token[1:]
        if field == "p":
            if current is not None:
                entries.append(ProcessInfo(current.pid, current.command, current.user, current_paths))
            current_paths = []
            pid = _lsof_owner_pid(value)
            current = ProcessInfo(pid=pid, command="", user="", paths=[])
        elif current is None:
            continue
        else:
            _lsof_detail(current, field, value, current_paths)
    if current is not None:
        entries.append(ProcessInfo(current.pid, current.command, current.user, current_paths))
    if output.strip() and (not entries or any(not entry.paths for entry in entries)):
        raise RuntimeError("lsof ownership data is incomplete")
    return entries


UNIT_REGEX = re.compile(r"[●•]\s+([\w@.-]+\.service)")


def _systemd_unit_for_pid(pid: int) -> str | None:
    try:
        cgroup = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8")
        for line in cgroup.splitlines():
            for component in line.split(":", 2)[-1].split("/"):
                if component.endswith(".service"):
                    return component
    except OSError:
        pass
    try:
        out = subprocess.check_output(
            ["systemctl", "status", "--no-pager", "--lines=0", str(pid)],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    match = UNIT_REGEX.search(out)
    return match.group(1) if match else None


def _holder_dict(proc: ProcessInfo, path: str) -> dict[str, Any]:
    return {
        "pid": proc.pid,
        "cmd": proc.command or f"pid_{proc.pid}",
        "user": proc.user or "?",
        "path": path,
        "service": _systemd_unit_for_pid(proc.pid),
    }


RESOURCE_SPECS: dict[str, dict[str, Any]] = {
    "mic": {
        "label": "Microphone",
        "paths": ["/dev/snd/pcm*"],
        "matcher": re.compile(r"/dev/snd/pcmC\d+D\d+c"),
        "release": {
            "kind": "alsa",
            "args": ["--capture", _default_capture_dev],
        },
    },
    "speaker": {
        "label": "Speaker",
        "paths": ["/dev/snd/pcm*"],
        "matcher": re.compile(r"/dev/snd/pcmC\d+D\d+p"),
        "release": {
            "kind": "alsa",
            "args": ["--playback", _default_playback_dev],
        },
    },
    "camera": {
        "label": "Camera",
        "paths": ["/dev/video*"],
        "matcher": re.compile(r"/dev/video\d+"),
        "release": {
            "kind": "camera",
            "args": ["--device", os.getenv("RESOURCE_CAMERA_DEVICE", "/dev/video0")],
        },
    },
    "lcd": {
        "label": 'LCD 2"',
        "paths": ["/dev/spidev0.*", "/dev/fb1", "/dev/fb0"],
        "matcher": re.compile(r"/dev/(spidev\d+\.\d+|fb[01])"),
        "release": {
            "kind": "lcd",
            "args": ["off"],
        },
    },
    "uart": {
        "label": "UART — executor only",
        "paths": ["/dev/ttyAMA0"],
        "matcher": re.compile(r"/dev/ttyAMA0$"),
    },
}

VISION_RESOURCE_GUARD = os.path.join(BASE_DIR, "scripts", "vision-resource-guard.sh")


def _run_guard(action: str) -> dict[str, Any]:
    if action not in {"claim", "release"} or not os.path.isfile(VISION_RESOURCE_GUARD):
        return {"ok": False, "error": "vision-resource-guard unavailable"}
    try:
        proc = subprocess.run(
            ["sudo", "-n", VISION_RESOURCE_GUARD, action],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except FileNotFoundError:
        return {"ok": False, "error": "vision-resource-guard missing"}

    return {
        "ok": proc.returncode == 0,
        "rc": proc.returncode,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
    }


def available_resources() -> list[str]:
    return sorted(RESOURCE_SPECS.keys())


def _matching_holders(processes, matcher):
    holders = []
    for proc in processes:
        for path in proc.paths:
            if matcher.fullmatch(path):
                holders.append(_holder_dict(proc, path))
                break
    return holders


def inspect(resource: str) -> dict[str, Any]:
    if resource not in RESOURCE_SPECS:
        raise KeyError(f"unknown resource '{resource}'")

    spec = RESOURCE_SPECS[resource]
    paths = _existing_paths(spec["paths"])
    holders: list[dict[str, Any]] = []
    error: str | None = None
    try:
        processes = _run_lsof(paths)
        holders = _matching_holders(processes, spec["matcher"])
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        error = str(exc)

    state = "free"
    if error:
        state = "unknown"
    elif not paths:
        state = "unavailable"
    elif holders:
        state = "busy"
    return {
        "resource": resource,
        "label": spec["label"],
        "checked_at": time.time(),
        "holders": holders,
        "paths": paths,
        "observed_at": None if error else time.time(),
        "source": "lsof",
        "state": state,
        "free": None if error or not paths else not holders,
        "error": error,
    }


def _call_release(cmd: list[str]) -> dict[str, Any]:
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {
        "ok": proc.returncode == 0,
        "rc": proc.returncode,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
        "command": cmd,
    }


def release(
    resource: str, *, limit_pids: Iterable[int] | None = None, force: bool = False, operator_consent: bool = False
) -> dict[str, Any]:
    if resource not in RESOURCE_SPECS:
        raise KeyError(f"unknown resource '{resource}'")

    from common.service_catalog import PROTECTED_UNITS

    from .features_api import feature_manager

    try:
        with feature_manager.transaction():
            return _release_locked(resource, limit_pids, force, operator_consent, feature_manager, PROTECTED_UNITS)
    except OSError as exc:
        return {"ok": False, "error": "orchestration_lock_unavailable", "detail": str(exc)}


def _recorded_consumers(feature_manager, resource, consumers):
    # A separate maintenance CLI must also respect the API's recorded consumers.
    try:
        state = json.loads(feature_manager._state_path.read_text(encoding="utf-8"))
        recorded = state.get("resource_consumers", {}).get(resource, [])
        if not isinstance(recorded, list):
            raise ValueError("invalid recorded consumers")
        consumers = sorted(set(consumers + recorded))
    except FileNotFoundError:
        pass
    except (OSError, ValueError, AttributeError, TypeError):
        return None, {"ok": False, "error": "task_ownership_unknown", "resource": resource}
    return consumers, None


def _released_state(released, after):
    if released:
        return "released"
    return "unknown" if after.get("error") else "pending"


def _release_locked(resource, limit_pids, force, operator_consent, feature_manager, protected_units) -> dict:
    observed = inspect(resource)
    pids = sorted(set(limit_pids or []))
    consumers = feature_manager.resource_consumers().get(resource, [])
    consumers, ownership_error = _recorded_consumers(feature_manager, resource, consumers)
    if ownership_error is not None:
        return ownership_error
    plan = {
        "resource": resource,
        "owners": observed["holders"],
        "pids": pids,
        "effects": ["SIGTERM for selected observed owners; no SIGKILL; no service restart"],
        "consumers": consumers,
    }
    if resource in {"uart", "lcd"}:
        return {"ok": False, "error": "protected_resource", **plan}
    if not force or not operator_consent or not pids or any(not isinstance(pid, int) or pid <= 1 for pid in pids):
        return {"ok": False, "error": "manual_recovery_confirmation_required", **plan}
    if observed.get("state") in {"unknown", "unavailable"} or plan["consumers"]:
        return {"ok": False, "error": "ownership_unknown_or_in_use", **plan}
    owners = {owner["pid"]: owner for owner in observed["holders"]}
    if any(
        pid not in owners or not owners[pid].get("service") or owners[pid].get("service") in protected_units
        for pid in pids
    ):
        return {"ok": False, "error": "owner_mismatch_or_protected", **plan}
    result = _call_release(["sudo", "-n", "kill", "-TERM", "--", *(str(pid) for pid in pids)])
    if not result.get("ok"):
        return {**result, **plan, "signal_sent": False, "released": False}
    after = inspect(resource)
    released = after.get("free") is True and not after.get("error")
    return {
        **result,
        **plan,
        "ok": released,
        "signal_sent": True,
        "released": released,
        "pending": not released and not after.get("error"),
        "state": _released_state(released, after),
        "after": after,
        "error": after.get("error"),
    }


def to_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


def guard_camera(action: str) -> dict[str, Any]:
    """
    Wywołaj skrypt guardujący zasób kamery (claim/release).
    """
    return _run_guard(action)


__all__ = [
    "available_resources",
    "inspect",
    "release",
    "guard_camera",
]
