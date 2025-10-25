#!/usr/bin/env python3
"""
Google Home API integration module.
Handles OAuth 2.0 authentication and Smart Device Management API communication.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

logger = logging.getLogger(__name__)

# Configuration from environment variables
CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
PROJECT_ID = os.getenv("GOOGLE_PROJECT_ID", "")

# OAuth scopes
SCOPES = ["https://www.googleapis.com/auth/sdm.service"]

# API configuration
API_TIMEOUT = int(os.getenv("GOOGLE_API_TIMEOUT", "10"))

# Token storage path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
TOKEN_FILE = BASE_DIR / "config" / "local" / "google_tokens.json"

# API endpoints
API_BASE = "https://smartdevicemanagement.googleapis.com/v1"


def _ensure_token_dir():
    """Ensure token directory exists."""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)


def start_oauth_flow() -> dict[str, Any]:
    """
    Start OAuth 2.0 authorization flow using InstalledAppFlow.

    This method opens a local server to handle the OAuth callback automatically.
    The user will be prompted to open a browser and complete the authorization.

    Returns:
        Dictionary with status and message.
    """
    if not CLIENT_ID or not CLIENT_SECRET:
        raise ValueError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in environment variables")

    client_config = {
        "installed": {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost", "urn:ietf:wg:oauth:2.0:oob"],
        }
    }

    try:
        flow = InstalledAppFlow.from_client_config(
            client_config,
            scopes=SCOPES,
        )

        # Run local server to handle OAuth callback automatically
        # This will open the browser and wait for user to complete authorization
        logger.info("Starting OAuth flow with local server...")
        credentials = flow.run_local_server(
            port=8080,
            access_type="offline",
            prompt="consent",
        )

        # Save refresh token
        _ensure_token_dir()
        token_data = {
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": credentials.scopes,
        }

        with open(TOKEN_FILE, "w") as f:
            json.dump(token_data, f, indent=2)

        logger.info(f"OAuth tokens saved to {TOKEN_FILE}")
        return {"ok": True, "message": "Authentication successful"}

    except Exception as e:
        logger.error(f"OAuth flow error: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


def is_authenticated() -> bool:
    """
    Check if user is authenticated (has valid refresh token).

    Returns:
        True if refresh token exists, False otherwise.
    """
    return TOKEN_FILE.exists()


def _load_credentials() -> Credentials | None:
    """
    Load credentials from token file.

    Returns:
        Credentials object or None if not available.
    """
    if not TOKEN_FILE.exists():
        return None

    try:
        with open(TOKEN_FILE) as f:
            token_data = json.load(f)

        creds = Credentials(
            token=None,
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=token_data.get("scopes"),
        )

        return creds
    except Exception as e:
        logger.error(f"Error loading credentials: {e}", exc_info=True)
        return None


def refresh_access_token() -> str | None:
    """
    Refresh the access token using the stored refresh token.

    Returns:
        New access token or None if refresh failed.
    """
    creds = _load_credentials()
    if not creds:
        logger.error("No credentials available to refresh")
        return None

    try:
        if not creds.valid:
            creds.refresh(Request())
            logger.info("Access token refreshed successfully")
        return creds.token
    except Exception as e:
        logger.error(f"Error refreshing token: {e}", exc_info=True)
        return None


def get_devices() -> dict[str, Any]:
    """
    Get list of devices from Smart Device Management API.

    Returns:
        Dictionary with devices list or error.
    """
    if not PROJECT_ID:
        return {"ok": False, "error": "GOOGLE_PROJECT_ID not set"}

    token = refresh_access_token()
    if not token:
        return {"ok": False, "error": "Not authenticated or token refresh failed"}

    try:
        url = f"{API_BASE}/enterprises/{PROJECT_ID}/devices"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        response = requests.get(url, headers=headers, timeout=API_TIMEOUT)

        if response.status_code == 401:
            return {"ok": False, "error": "Unauthorized", "status_code": 401}

        response.raise_for_status()
        data = response.json()

        devices = data.get("devices", [])
        logger.info(f"Retrieved {len(devices)} devices")

        return {"ok": True, "devices": devices}

    except requests.exceptions.RequestException as e:
        logger.error(f"Error getting devices: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


def send_command(device_id: str, command: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Send command to a device.

    Args:
        device_id: Full device ID (enterprises/.../devices/...)
        command: Command name (e.g., 'action.devices.commands.OnOff')
        params: Command parameters

    Returns:
        Dictionary with command result or error.
    """
    token = refresh_access_token()
    if not token:
        return {"ok": False, "error": "Not authenticated or token refresh failed"}

    try:
        url = f"{API_BASE}/{device_id}:executeCommand"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        payload = {
            "command": command,
            "params": params or {},
        }

        response = requests.post(url, headers=headers, json=payload, timeout=API_TIMEOUT)

        if response.status_code == 401:
            return {"ok": False, "error": "Unauthorized", "status_code": 401}

        response.raise_for_status()

        logger.info(f"Command '{command}' sent to device {device_id}")
        return {"ok": True, "result": response.json() if response.text else {}}

    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending command: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}
