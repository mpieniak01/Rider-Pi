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
        "aliases": {"wm8960_in": "hw:wm8960soundcard,0", "wm8960_out": "hw:wm8960soundcard,0"},
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

        logger.event("alsa.probe.success", cards_count=len(result["cards"]), devices_count=len(result["devices"]))
    except Exception as e:
        logger.event("alsa.probe.error", error=str(e))

    return result


def resolved_alsa(name: str | None) -> str | None:
    """Resolve ALSA device name/alias to full device specification."""
    if not name:
        return None

    aliases = {
        "wm8960_in": "hw:wm8960soundcard,0",
        "wm8960_out": "hw:wm8960soundcard,0",
        "wm8960soundcard": "hw:wm8960soundcard,0",
    }
    return aliases.get(name, name)


def _kill_processes_using_device(device_pattern: str) -> int:
    """Kill processes that may be using ALSA devices."""
    # Guard pod testy/CI: omijamy lsof, żeby nie wisieć
    if os.getenv("ALSA_SKIP_LSOF") == "1" or os.getenv("PYTEST_CURRENT_TEST"):
        logger.event("alsa.lsof.skip", reason="test_env_or_envflag")
        return 0

    killed = 0
    try:
        proc = subprocess.run(["lsof", "/dev/snd/*"], capture_output=True, text=True, timeout=2)
        if proc.returncode == 0:
            lines = proc.stdout.splitlines()[1:]  # Skip header
            for line in lines:
                parts = line.split()
                if len(parts) >= 2:
                    pid = parts[1]
                    command = parts[0]
                    if any(cmd in command.lower() for cmd in ["arecord", "aplay", "apps.voice.cli"]):
                        try:
                            subprocess.run(["kill", "-TERM", pid], timeout=2)
                            time.sleep(0.2)
                            check = subprocess.run(["kill", "-0", pid], capture_output=True, timeout=1)
                            if check.returncode == 0:
                                subprocess.run(["kill", "-KILL", pid], timeout=2)
                            killed += 1
                            logger.event("alsa.process_killed", pid=pid, command=command)
                        except Exception as e:
                            logger.event("alsa.kill_error", pid=pid, error=str(e))
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
        cmd = ["timeout", "2", "aplay", "-D", device, "-f", "S16_LE", "-r", "16000", "-c", "2", "/dev/null"]

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
        ALSAError = pkg.ALSAError  # type: ignore[no-redef]
    except Exception:
        from .errors import ALSAError  # type: ignore[no-redef]

    raise ALSAError(msg)  # type: ignore[misc]


def ensure_free(
    capture_dev: str | None = None,
    playback_dev: str | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Ensure ALSA devices are free and accessible."""
    result: dict[str, Any] = {"capture_free": True, "playback_free": True, "processes_killed": 0, "errors": []}

    capture_resolved = resolved_alsa(capture_dev) if capture_dev else None
    playback_resolved = resolved_alsa(playback_dev) if playback_dev else None

    logger.event("alsa.ensure_free.start", capture=capture_resolved, playback=playback_resolved, force=force)

    if capture_resolved:
        result["capture_free"] = _test_device_access(capture_resolved, "capture")
    if playback_resolved:
        result["playback_free"] = _test_device_access(playback_resolved, "playback")

    devices_blocked = not result["capture_free"] or not result["playback_free"]

    if (force or devices_blocked) and (capture_resolved or playback_resolved):
        device_pattern = "wm8960"
        result["processes_killed"] = _kill_processes_using_device(device_pattern)

        if result["processes_killed"] > 0:
            time.sleep(0.2)

        if capture_resolved:
            result["capture_free"] = _test_device_access(capture_resolved, "capture")
        if playback_resolved:
            result["playback_free"] = _test_device_access(playback_resolved, "playback")

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
        _kill_processes_using_device("wm8960")
        time.sleep(0.2)
        logger.event("alsa.reset_streams.complete")
    except Exception as e:
        logger.event("alsa.reset_streams.error", error=str(e))
