"""ALSA device management and pre-flight checks for Rider-Pi voice assistant.

Provides utilities for:
- Probing available ALSA devices and aliases
- Pre-flight device availability checks
- Safe process cleanup (arecord, aplay)
- Device alias resolution (wm8960_in, wm8960_out)
"""

from __future__ import annotations

import subprocess
import time
from typing import Any

from .. import voice_logging
from ..common import ensure_event_logger

logger = ensure_event_logger(voice_logging.get_logger(__name__))


class ALSAError(RuntimeError):
    """ALSA-related errors."""

    pass


def probe_devices() -> dict[str, Any]:
    """Probe available ALSA devices and log information.

    Returns:
        Dictionary with device information including:
        - cards: List of sound cards
        - devices: Available PCM devices
        - aliases: Known device aliases
    """
    result = {
        "cards": [],
        "devices": [],
        "aliases": {"wm8960_in": "hw:wm8960soundcard,0", "wm8960_out": "hw:wm8960soundcard,0"},
    }

    try:
        # List sound cards
        proc = subprocess.run(["cat", "/proc/asound/cards"], capture_output=True, text=True, timeout=5)
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                line = line.strip()
                if line and not line.startswith("---"):
                    result["cards"].append(line)

        # List PCM devices
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
    """Resolve ALSA device name/alias to full device specification.

    Args:
        name: Device name or alias (e.g., "wm8960_in", "hw:wm8960soundcard,0")

    Returns:
        Resolved device name or None if not resolvable
    """
    if not name:
        return None

    # Known aliases (migrated from playback.py)
    aliases = {
        "wm8960_in": "hw:wm8960soundcard,0",
        "wm8960_out": "hw:wm8960soundcard,0",
        "wm8960soundcard": "hw:wm8960soundcard,0",
    }

    return aliases.get(name, name)


def _kill_processes_using_device(device_pattern: str) -> int:
    """Kill processes using ALSA device.

    Args:
        device_pattern: Device pattern to match (e.g., "wm8960")

    Returns:
        Number of processes killed
    """
    killed = 0

    try:
        # Find processes using the device
        proc = subprocess.run(["lsof", "/dev/snd/*"], capture_output=True, text=True, timeout=10)

        if proc.returncode == 0:
            lines = proc.stdout.splitlines()[1:]  # Skip header

            for line in lines:
                parts = line.split()
                if len(parts) >= 2:
                    pid = parts[1]
                    command = parts[0]

                    # Target specific processes that might block audio
                    if any(cmd in command.lower() for cmd in ["arecord", "aplay", "apps.voice.cli"]):
                        try:
                            subprocess.run(["kill", "-TERM", pid], timeout=5)
                            time.sleep(0.5)

                            # Check if still running, force kill if needed
                            check = subprocess.run(["kill", "-0", pid], capture_output=True, timeout=2)
                            if check.returncode == 0:
                                subprocess.run(["kill", "-KILL", pid], timeout=5)

                            killed += 1
                            logger.event("alsa.process_killed", pid=pid, command=command)

                        except Exception as e:
                            logger.event("alsa.kill_error", pid=pid, error=str(e))

    except Exception as e:
        logger.event("alsa.lsof_error", error=str(e))

    return killed


def _test_device_access(device: str, mode: str) -> bool:
    """Test if device can be opened for capture/playback.

    Args:
        device: ALSA device name
        mode: "capture" or "playback"

    Returns:
        True if device is accessible
    """
    if mode == "capture":
        # Quick test with arecord
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
    else:  # playback
        cmd = ["timeout", "2", "aplay", "-D", device, "-f", "S16_LE", "-r", "16000", "-c", "2", "/dev/null"]

    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=3)
        return proc.returncode == 0
    except Exception:
        return False


def ensure_free(
    capture_dev: str | None = None, playback_dev: str | None = None, *, force: bool = False
) -> dict[str, Any]:
    """Ensure ALSA devices are free and accessible.

    Args:
        capture_dev: Capture device name/alias
        playback_dev: Playback device name/alias
        force: If True, kill processes blocking devices

    Returns:
        Dictionary with status information

    Raises:
        ALSAError: If devices are not accessible after cleanup
    """
    result = {"capture_free": True, "playback_free": True, "processes_killed": 0, "errors": []}

    # Resolve device names
    capture_resolved = resolved_alsa(capture_dev) if capture_dev else None
    playback_resolved = resolved_alsa(playback_dev) if playback_dev else None

    logger.event("alsa.ensure_free.start", capture=capture_resolved, playback=playback_resolved, force=force)

    # Test initial accessibility
    if capture_resolved:
        result["capture_free"] = _test_device_access(capture_resolved, "capture")

    if playback_resolved:
        result["playback_free"] = _test_device_access(playback_resolved, "playback")

    # If force=True or devices are blocked, try to free them
    devices_blocked = not result["capture_free"] or not result["playback_free"]

    if (force or devices_blocked) and (capture_resolved or playback_resolved):
        # Determine device pattern for process killing
        device_pattern = "wm8960"  # Default pattern

        result["processes_killed"] = _kill_processes_using_device(device_pattern)

        # Wait a bit for cleanup
        if result["processes_killed"] > 0:
            time.sleep(1)

        # Re-test accessibility
        if capture_resolved:
            result["capture_free"] = _test_device_access(capture_resolved, "capture")

        if playback_resolved:
            result["playback_free"] = _test_device_access(playback_resolved, "playback")

    # Check final status
    if capture_resolved and not result["capture_free"]:
        error = f"Capture device {capture_resolved} is not accessible"
        result["errors"].append(error)

    if playback_resolved and not result["playback_free"]:
        error = f"Playback device {playback_resolved} is not accessible"
        result["errors"].append(error)

    # Log final status
    logger.event(
        "alsa.ensure_free.complete",
        capture_free=result["capture_free"],
        playback_free=result["playback_free"],
        processes_killed=result["processes_killed"],
        errors=len(result["errors"]),
    )

    if result["errors"]:
        raise ALSAError("; ".join(result["errors"]))

    return result


def reset_streams() -> None:
    """Reset/cleanup after audio streaming operations.

    This function should be called in finally blocks to ensure
    clean state after voice operations.
    """
    try:
        # Kill any remaining test processes
        _kill_processes_using_device("wm8960")

        # Brief wait for cleanup
        time.sleep(0.2)

        logger.event("alsa.reset_streams.complete")

    except Exception as e:
        logger.event("alsa.reset_streams.error", error=str(e))
