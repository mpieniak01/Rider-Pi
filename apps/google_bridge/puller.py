#!/usr/bin/env python3
"""
Google Bridge Puller - Cyclic worker that polls Google data and updates local cache.

This worker runs independently and writes status and data snapshots to local files.
It does not affect other services and can be safely enabled/disabled.

Environment variables:
    GOOGLE_POLL_S: Polling interval in seconds (default: 300)
    GOOGLE_ENABLED: Enable/disable the worker (default: 1)
    DATA_DIR: Base data directory (default: ~/robot/data)
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("google_bridge.puller")

# Configuration from environment
GOOGLE_POLL_S = int(os.getenv("GOOGLE_POLL_S", "300"))  # 5 minutes default
GOOGLE_ENABLED = os.getenv("GOOGLE_ENABLED", "1") == "1"
DATA_DIR = Path(os.getenv("DATA_DIR", Path.home() / "robot" / "data"))
GOOGLE_DATA_DIR = DATA_DIR / "google"

# Ensure data directory exists
GOOGLE_DATA_DIR.mkdir(parents=True, exist_ok=True)

STATUS_FILE = GOOGLE_DATA_DIR / "status.json"
LAST_FILE = GOOGLE_DATA_DIR / "last.json"

# Global shutdown flag
_shutdown = False


def signal_handler(signum: int, frame: Any) -> None:
    """Handle shutdown signals gracefully."""
    global _shutdown
    logger.info(f"Received signal {signum}, shutting down...")
    _shutdown = True


def write_status(state: str, timestamp: float, errors_24h: int = 0, requests_24h: int = 0) -> None:
    """Write status to status.json file.

    Args:
        state: One of: enabled, ok, error, off
        timestamp: Unix timestamp of last update
        errors_24h: Number of errors in last 24h
        requests_24h: Number of requests in last 24h
    """
    status = {
        "state": state,
        "timestamp": timestamp,
        "metrics": {"errors_24h": errors_24h, "requests_24h": requests_24h},
    }
    try:
        STATUS_FILE.write_text(json.dumps(status, indent=2))
        logger.debug(f"Status updated: {state}")
    except Exception as e:
        logger.error(f"Failed to write status: {e}")


def write_snapshot(data: dict[str, Any] | None = None, error: str | None = None) -> None:
    """Write data snapshot or error to last.json file.

    Args:
        data: Snapshot data to write (optional)
        error: Error message if snapshot failed (optional)
    """
    if error:
        snapshot = {"error": error, "timestamp": time.time()}
    elif data:
        snapshot = {"data": data, "timestamp": time.time()}
    else:
        snapshot = {"error": "no_data", "timestamp": time.time()}

    try:
        LAST_FILE.write_text(json.dumps(snapshot, indent=2))
        logger.debug("Snapshot updated")
    except Exception as e:
        logger.error(f"Failed to write snapshot: {e}")


def pseudocall_google() -> dict[str, Any]:
    """Simulate a Google API call.

    This is a placeholder for actual Google API integration.
    For now, it returns controlled test data.

    Returns:
        Dictionary with simulated Google data
    """
    # This is where real Google API calls would go
    # For now, return a controlled test response
    return {
        "service": "google_feed",
        "status": "pseudocall",
        "timestamp": time.time(),
        "message": "This is a placeholder for Google API integration",
    }


def poll_google() -> tuple[bool, dict[str, Any] | None, str | None]:
    """Poll Google for data.

    Returns:
        Tuple of (success, data, error_message)
    """
    try:
        data = pseudocall_google()
        return True, data, None
    except Exception as e:
        logger.error(f"Google poll failed: {e}")
        return False, None, str(e)


def main() -> int:
    """Main worker loop."""
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("Google Bridge Puller starting...")
    logger.info(f"Poll interval: {GOOGLE_POLL_S}s")
    logger.info(f"Data directory: {GOOGLE_DATA_DIR}")
    logger.info(f"Enabled: {GOOGLE_ENABLED}")

    # Check if disabled
    if not GOOGLE_ENABLED:
        logger.info("Google Bridge is disabled (GOOGLE_ENABLED=0)")
        write_status("off", time.time())
        # Stay alive but idle
        while not _shutdown:
            time.sleep(1)
        return 0

    # Counters for metrics
    errors_24h = 0
    requests_24h = 0
    last_reset = time.time()

    # Initial status
    write_status("enabled", time.time())

    # Main loop
    while not _shutdown:
        try:
            # Reset counters every 24h
            if time.time() - last_reset > 86400:
                errors_24h = 0
                requests_24h = 0
                last_reset = time.time()

            # Poll Google
            logger.info("Polling Google...")
            requests_24h += 1
            success, data, error = poll_google()

            if success:
                write_status("ok", time.time(), errors_24h, requests_24h)
                write_snapshot(data=data)
                logger.info("Poll successful")
            else:
                errors_24h += 1
                write_status("error", time.time(), errors_24h, requests_24h)
                write_snapshot(error=error)
                logger.warning(f"Poll failed: {error}")

            # Wait for next poll
            logger.debug(f"Waiting {GOOGLE_POLL_S}s until next poll...")
            for _ in range(GOOGLE_POLL_S):
                if _shutdown:
                    break
                time.sleep(1)

        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")
            errors_24h += 1
            write_status("error", time.time(), errors_24h, requests_24h)
            write_snapshot(error=str(e))
            # Brief sleep before retry
            time.sleep(5)

    logger.info("Google Bridge Puller stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
