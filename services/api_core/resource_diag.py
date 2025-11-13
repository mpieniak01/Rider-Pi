#!/usr/bin/env python3
"""Diagnostyka i zwalnianie zasobów sprzętowych (audio/kamera).

Udostępnia wspólne funkcje wykorzystywane przez API oraz skrypt CLI
``scripts/resource_diag.py``. Podejście celowo jest możliwie proste:
wykorzystujemy `lsof` do wykrywania blokujących procesów, a do
zwalniania posługujemy się istniejącymi skryptami (ALSA preflight oraz
`sys_camera-free.sh`).
"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from . import compat as C


@dataclass
class ProcessInfo:
    pid: int
    command: str
    user: str
    paths: list[str]


ALSA_PREFLIGHT = os.path.join(C.BASE_DIR, "config", "alsa", "preflight.sh")
CAMERA_FREE = os.path.join(C.BASE_DIR, "scripts", "sys_camera-free.sh")
LCD_CONTROL = os.path.join(C.BASE_DIR, "scripts", "sys_lcd-control.py")


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
    cmd = ["lsof", "-FpcuLn0", "--", *paths]
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

    # lsof zwraca rc=1 gdy brak pasujących procesów — traktujemy to jak „brak danych”
    if proc.returncode not in (0, 1):
        msg = proc.stderr.strip() or proc.stdout.strip() or "unknown error"
        raise RuntimeError(f"lsof failed (rc={proc.returncode}): {msg}")

    entries: list[ProcessInfo] = []
    current: ProcessInfo | None = None
    current_paths: list[str] = []
    for token in proc.stdout.split("\0"):
        if not token:
            continue
        field = token[0]
        value = token[1:]
        if field == "p":
            if current is not None:
                entries.append(ProcessInfo(current.pid, current.command, current.user, current_paths))
            current_paths = []
            try:
                pid = int(value)
            except ValueError:
                continue
            current = ProcessInfo(pid=pid, command="", user="", paths=[])
        elif current is None:
            continue
        elif field == "c":
            current.command = value
        elif field == "L":
            current.user = value
        elif field == "n":
            current_paths.append(value)
    if current is not None:
        entries.append(ProcessInfo(current.pid, current.command, current.user, current_paths))
    return entries


UNIT_REGEX = re.compile(r"[●•]\s+([\w@.-]+\.service)")


def _systemd_unit_for_pid(pid: int) -> str | None:
    try:
        out = subprocess.check_output(
            ["systemctl", "status", "--no-pager", "--lines=0", f"--pid={pid}"],
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
        "paths": ["/dev/video*", "/dev/spidev0.*"],
        "matcher": re.compile(r"/(video|spidev)"),
        "release": {
            "kind": "camera",
            "args": ["--device", os.getenv("RESOURCE_CAMERA_DEVICE", "/dev/video0"), "--with-spi"],
        },
    },
    "lcd": {
        "label": 'LCD 2"',
        "paths": ["/dev/spidev0.*", "/dev/fb1", "/dev/fb0"],
        "matcher": re.compile(r"/(spidev|fb[01])"),
        "release": {
            "kind": "lcd",
            "args": ["off"],
        },
    },
}


def available_resources() -> list[str]:
    return sorted(RESOURCE_SPECS.keys())


def inspect(resource: str) -> dict[str, Any]:
    if resource not in RESOURCE_SPECS:
        raise KeyError(f"unknown resource '{resource}'")

    spec = RESOURCE_SPECS[resource]
    paths = _existing_paths(spec["paths"])
    holders: list[dict[str, Any]] = []
    error: str | None = None
    try:
        processes = _run_lsof(paths)
        matcher: re.Pattern[str] = spec["matcher"]
        for proc in processes:
            for path in proc.paths:
                if matcher.search(path):
                    holders.append(_holder_dict(proc, path))
                    break
    except RuntimeError as exc:
        error = str(exc)

    return {
        "resource": resource,
        "label": spec["label"],
        "checked_at": time.time(),
        "holders": holders,
        "free": not holders,
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


def release(resource: str, *, limit_pids: Iterable[int] | None = None) -> dict[str, Any]:
    if resource not in RESOURCE_SPECS:
        raise KeyError(f"unknown resource '{resource}'")

    spec = RESOURCE_SPECS[resource]
    release_spec = spec.get("release")
    if not release_spec:
        return {"ok": False, "error": "resource not releasable"}

    limit_args: list[str] = []
    if limit_pids:
        flag = "--limit-pid" if release_spec["kind"] == "alsa" else "--pid"
        for pid in limit_pids:
            limit_args.extend([flag, str(pid)])

    if release_spec["kind"] == "alsa":
        args = release_spec["args"]
        resolved_args: list[str] = []
        for arg in args:
            resolved_args.append(arg() if callable(arg) else arg)
        cmd = [ALSA_PREFLIGHT, "--force", *resolved_args, *limit_args]
        return _call_release(cmd)

    if release_spec["kind"] == "camera":
        args = [arg() if callable(arg) else arg for arg in release_spec["args"]]
        cmd = [CAMERA_FREE, *args, *limit_args]
        return _call_release(cmd)

    if release_spec["kind"] == "lcd":
        args = [arg() if callable(arg) else arg for arg in release_spec["args"]]
        cmd = ["sudo", "-n", "python3", LCD_CONTROL, *args]
        return _call_release(cmd)

    return {"ok": False, "error": "unsupported release kind"}


def to_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


__all__ = [
    "available_resources",
    "inspect",
    "release",
]
