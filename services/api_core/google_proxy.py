#!/usr/bin/env python3
"""
Google Proxy API - Read-only access to Google feed cache.

Provides endpoints to read status and data snapshots from the local Google feed cache.
This module never makes live calls to Google - it only reads local files.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)

# Configuration
DATA_DIR = Path(os.getenv("DATA_DIR", Path.home() / "robot" / "data"))
GOOGLE_DATA_DIR = DATA_DIR / "google"
STATUS_FILE = GOOGLE_DATA_DIR / "status.json"
LAST_FILE = GOOGLE_DATA_DIR / "last.json"

# Create blueprint
google_proxy = Blueprint("google_proxy", __name__, url_prefix="/api/google")


def _read_json_file(file_path: Path, default: dict | None = None) -> dict:
    """Read and parse a JSON file, return default on error.

    Args:
        file_path: Path to JSON file
        default: Default value to return on error

    Returns:
        Parsed JSON data or default value
    """
    if default is None:
        default = {}

    try:
        if not file_path.exists():
            return default
        content = file_path.read_text()
        return json.loads(content)
    except Exception as e:
        logger.warning(f"Failed to read {file_path}: {e}")
        return default


@google_proxy.route("/status", methods=["GET"])
def get_status():
    """Get Google feed status.

    Returns:
        JSON response with status information:
        - state: enabled|ok|error|off
        - timestamp: last update timestamp
        - metrics: errors_24h, requests_24h
    """
    # Read status file with fallback
    status = _read_json_file(
        STATUS_FILE, {"state": "off", "timestamp": 0, "metrics": {"errors_24h": 0, "requests_24h": 0}}
    )

    # Ensure status is never 500 - always return valid JSON
    return jsonify(status), 200


@google_proxy.route("/raw/last.json", methods=["GET"])
def get_last_snapshot():
    """Get last data snapshot from Google feed.

    Returns:
        JSON response with last snapshot or 404 if no snapshot available
    """
    # Read snapshot file
    snapshot = _read_json_file(LAST_FILE)

    # If file doesn't exist or is empty, return 404
    if not snapshot:
        return jsonify({"error": "no_snapshot"}), 404

    # Return snapshot (which may contain error or data)
    return jsonify(snapshot), 200
