# apps/voice/audio/alsa.py
"""ALSA device management and pre-flight checks for Rider-Pi voice assistant.

Provides utilities for:
- Probing available ALSA devices and aliases
- Pre-flight device availability checks
- Safe process cleanup (arecord, aplay)
- Device alias resolution (wm8960_in, wm8960_out)
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any

from .. import voice_logging
from ..common import ensure_event_logger

_WM8960_DEVICE = "hw:wm8960soundcard,0"

logger = ensure_event_logger(voice_logging.get_logger(__name__))

__all__ = [
    "probe_devices",
    "resolved_alsa",
    "ensure_free",
    "reset_streams",
]


def probe_devices() -> dict[str, Any]:
    """Probe available ALSA devices and log information."""
    result: dict[str, Any] = {
        "cards": [],
        "devices": [],
        "aliases": {
            "wm8960_in": _WM8960_DEVICE,
            "wm8960_out": _WM8960_DEVICE,
        },
    }

    try:
        proc = subprocess.run(["cat", "/proc/asound/cards"], capture_output=True, text=True, timeout=5)
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                line = line.strip()
                if line and not line.startswith("---"):
                    result["cards"].append(line)

        proc = subprocess.run(["aplay", "-l"], capture_output=True, text=True, timeout=5)
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                if "device" in line.lower():
                    result["devices"].append(line.strip())

        logger.event(
            "alsa.probe.success",
            cards_count=len(result["cards"]),
            devices_count=len(result["devices"]),
        )
    except Exception as e:
        logger.event("alsa.probe.error", error=str(e))

    return result


def resolved_alsa(name: str | None) -> str | None:
    """Resolve ALSA device name/alias to full device specification."""
    if not name:
        return None

    aliases = {
        "wm8960_in": _WM8960_DEVICE,
        "wm8960_out": _WM8960_DEVICE,
        "wm8960soundcard": _WM8960_DEVICE,
    }
    return aliases.get(name, name)


def _terminate_alsa_process(pid, command):
    try:
        subprocess.run(["kill", "-TERM", pid], timeout=2)
        time.sleep(0.2)
        check = subprocess.run(["kill", "-0", pid], capture_output=True, timeout=1)
        if check.returncode == 0:
            subprocess.run(["kill", "-KILL", pid], timeout=2)
        logger.event("alsa.process_killed", pid=pid, command=command)
        return True
    except Exception as exc:
        logger.event("alsa.kill_error", pid=pid, error=str(exc))
        return False


def _voice_processes_from_lsof(output):
    for line in output.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        command, pid = parts[:2]
        if any(name in command.lower() for name in ("arecord", "aplay", "apps.voice.cli")):
            yield pid, command


def _kill_processes_using_device() -> int:
    """Kill processes that may be using ALSA devices."""
    # Guard pod testy/CI: omijamy lsof, żeby nie wisieć
    if os.getenv("ALSA_SKIP_LSOF") == "1" or os.getenv("PYTEST_CURRENT_TEST"):
        logger.event("alsa.lsof.skip", reason="test_env_or_envflag")
        return 0

    killed = 0
    try:
        proc = subprocess.run(["lsof", "/dev/snd/*"], capture_output=True, text=True, timeout=2)
        if proc.returncode == 0:
            for pid, command in _voice_processes_from_lsof(proc.stdout):
                if _terminate_alsa_process(pid, command):
                    killed += 1

    except Exception as e:
        logger.event("alsa.lsof_error", error=str(e))

    return killed


def _test_device_access(device: str, mode: str) -> bool:
    """Test if device can be opened for capture/playback."""
    if mode == "capture":
        cmd = [
            "timeout",
            "2",
            "arecord",
            "-D",
            device,
            "-f",
            "S16_LE",
            "-r",
            "16000",
            "-c",
            "2",
            "-t",
            "raw",
            "/dev/null",
        ]
    else:
        cmd = [
            "timeout",
            "2",
            "aplay",
            "-D",
            device,
            "-f",
            "S16_LE",
            "-r",
            "16000",
            "-c",
            "2",
            "/dev/null",
        ]

    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=3)
        return proc.returncode == 0
    except Exception:
        return False


def _raise_alsa_error(msg: str) -> None:
    """Raise the canonical ALSAError expected by tests.

    Priorytet: `apps.voice.errors.ALSAError` (tak importuje test),
    fallback: lokalna `apps.voice.audio.errors.ALSAError` gdy bardzo wczesny import.
    """
    try:
        import importlib

        # Test używa: from apps.voice.errors import ALSAError
        pkg = importlib.import_module("apps.voice.errors")
        error_type = pkg.ALSAError
    except Exception:
        from .errors import ALSAError as error_type

    raise error_type(msg)


def _check_alsa_access(result, capture, playback):
    for mode, device in (("capture", capture), ("playback", playback)):
        if device:
            result[f"{mode}_free"] = _test_device_access(device, mode)


def ensure_free(
    capture_dev: str | None = None,
    playback_dev: str | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Ensure ALSA devices are free and accessible."""
    result: dict[str, Any] = {
        "capture_free": True,
        "playback_free": True,
        "processes_killed": 0,
        "errors": [],
    }

    capture_resolved = resolved_alsa(capture_dev) if capture_dev else None
    playback_resolved = resolved_alsa(playback_dev) if playback_dev else None

    logger.event(
        "alsa.ensure_free.start",
        capture=capture_resolved,
        playback=playback_resolved,
        force=force,
    )

    _check_alsa_access(result, capture_resolved, playback_resolved)

    devices_blocked = not result["capture_free"] or not result["playback_free"]

    if (force or devices_blocked) and (capture_resolved or playback_resolved):
        result["processes_killed"] = _kill_processes_using_device()

        if result["processes_killed"] > 0:
            time.sleep(0.2)

        _check_alsa_access(result, capture_resolved, playback_resolved)

    if capture_resolved and not result["capture_free"]:
        result["errors"].append(f"Capture device {capture_resolved} is not accessible")
    if playback_resolved and not result["playback_free"]:
        result["errors"].append(f"Playback device {playback_resolved} is not accessible")

    logger.event(
        "alsa.ensure_free.complete",
        capture_free=result["capture_free"],
        playback_free=result["playback_free"],
        processes_killed=result["processes_killed"],
        errors=len(result["errors"]),
    )

    if result["errors"]:
        _raise_alsa_error("; ".join(result["errors"]))

    return result


def reset_streams() -> None:
    """Reset/cleanup after audio streaming operations."""
    try:
        _kill_processes_using_device()
        time.sleep(0.2)
        logger.event("alsa.reset_streams.complete")
    except Exception as e:
        logger.event("alsa.reset_streams.error", error=str(e))
