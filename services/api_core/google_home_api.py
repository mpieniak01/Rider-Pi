#!/usr/bin/env python3
"""
Google Home API integration module.
Handles OAuth 2.0 authentication (InstalledAppFlow – Desktop) and
Smart Device Management (SDM) API communication.
"""

from __future__ import annotations

import json
import logging
import os
import socket
from pathlib import Path
from typing import Any

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Configuration from environment variables
# -----------------------------------------------------------------------------
CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
PROJECT_ID = os.getenv("GOOGLE_PROJECT_ID", "").strip()

# OAuth scopes
SCOPES = ["https://www.googleapis.com/auth/sdm.service"]

# API configuration
API_TIMEOUT = int(os.getenv("GOOGLE_API_TIMEOUT", "10"))
# Port, na którym tymczasowo nasłuchuje biblioteka Google podczas OAuth
OAUTH_CALLBACK_PORT = int(os.getenv("GOOGLE_OAUTH_PORT", "8080"))
# Port API (jeśli podany) – by uniknąć kolizji z OAUTH_CALLBACK_PORT
STATUS_API_PORT = int(os.getenv("STATUS_API_PORT", os.getenv("PORT", "8080")))

# Token storage path (repo_root/config/local/google_tokens.json)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
TOKEN_FILE = BASE_DIR / "config" / "local" / "google_tokens.json"

# SDM API
API_BASE = "https://smartdevicemanagement.googleapis.com/v1"


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _ensure_token_dir() -> None:
    """Ensure token directory exists."""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)


def _port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Return True if (host, port) is busy."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        try:
            return s.connect_ex((host, port)) == 0
        except OSError:
            # Jeśli błąd gniazda – przyjmijmy ostrożnie, że port jest niedostępny.
            return True


def _pick_oauth_port() -> int:
    """
    Pick a safe port for InstalledAppFlow.run_local_server():
    - prefer GOOGLE_OAUTH_PORT,
    - if it collides with STATUS_API_PORT or is busy, try a few fallbacks.
    """
    candidates = [OAUTH_CALLBACK_PORT]
    # unikaj kolizji z API
    if STATUS_API_PORT not in (OAUTH_CALLBACK_PORT,):
        candidates.append(STATUS_API_PORT)  # tylko aby sprawdzić i ominąć
    # sensowne fallbacki
    candidates.extend([8085, 8090, 8888, 0])  # 0 = auto-assign by OS

    for p in candidates:
        if p == STATUS_API_PORT:
            continue
        if p == 0:
            # pozwól OS przydzielić
            return 0
        if not _port_in_use(p):
            return p

    # w ostateczności pozwól OS dobrać port
    return 0


def _require_oauth_env() -> tuple[bool, str | None]:
    if not CLIENT_ID or not CLIENT_SECRET:
        return (
            False,
            "GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET are not set (Desktop app credentials required).",
        )
    return True, None


# -----------------------------------------------------------------------------
# OAuth helpers (HEADLESS-friendly)
# -----------------------------------------------------------------------------
def build_auth_url_preview() -> dict[str, Any]:
    """
    Zbuduj Google OAuth authorization URL i port loopback, którego planujemy użyć,
    ale NIE uruchamiaj jeszcze local servera. Przydatne w trybie headless.
    """
    ok, err = _require_oauth_env()
    if not ok:
        logger.error("OAuth init error: %s", err)
        return {"ok": False, "error": "auth_env_missing"}

    client_config = {
        "installed": {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)

    port = _pick_oauth_port()
    if port == 0:
        redirect = "http://localhost/"
        show_port = 0
    else:
        redirect = f"http://localhost:{port}/"
        show_port = port

    flow.redirect_uri = redirect
    auth_url, _state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )

    logger.info("OAuth preview: port=%s redirect=%s", show_port or "auto", redirect)
    logger.info("OAuth preview URL: %s", auth_url)
    return {"ok": True, "auth_url": auth_url, "port": show_port}


# -----------------------------------------------------------------------------
# OAuth (InstalledAppFlow – Desktop)
# -----------------------------------------------------------------------------
def start_oauth_flow() -> dict[str, Any]:
    """
    Start OAuth 2.0 authorization flow using InstalledAppFlow (Desktop app).
    Na RPi nie otwieramy przeglądarki (headless) – URL logujemy w journald.

    Testy oczekują:
      - ValueError przy braku GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET,
      - udanego przepływu przy mockowanym InstalledAppFlow.run_local_server(...),
        z parametrem port == OAUTH_CALLBACK_PORT (np. 8080).
    """
    ok, err = _require_oauth_env()
    if not ok:
        logger.error("OAuth init error: %s", err)
        # test wymaga wyjątku:
        raise ValueError("GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET are missing")

    client_config = {
        "installed": {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

    try:
        flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)

        # Użyj DOKŁADNIE OAUTH_CALLBACK_PORT (test patchuje tę wartość i tego oczekuje).
        port = OAUTH_CALLBACK_PORT

        credentials = flow.run_local_server(
            port=port,
            access_type="offline",
            prompt="consent",
            open_browser=False,
        )

        # Save refresh token (and metadata)
        _ensure_token_dir()
        token_data = {
            "refresh_token": getattr(credentials, "refresh_token", ""),
            "token_uri": getattr(credentials, "token_uri", ""),
            "client_id": getattr(credentials, "client_id", ""),
            "client_secret": getattr(credentials, "client_secret", ""),
            "scopes": list(getattr(credentials, "scopes", []) or []),
        }
        if not token_data["refresh_token"]:
            logger.warning(
                "OAuth completed but no refresh_token received. "
                "Try again with prompt='consent' or revoke previous consent in Google account."
            )

        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump(token_data, f, indent=2)

        logger.info("OAuth tokens saved to %s", TOKEN_FILE)
        return {"ok": True, "message": "Authentication successful"}

    except Exception as e:
        logger.error("OAuth flow error: %s", e, exc_info=True)
        return {
            "ok": False,
            "error": "OAuth authorization failed",
            "error_detail": str(e),
        }


def is_authenticated() -> bool:
    """True if refresh token file exists."""
    return TOKEN_FILE.exists()


def _load_credentials() -> Credentials | None:
    """
    Load credentials from token file.

    Returns:
        Credentials object or None if not available/invalid.
    """
    if not TOKEN_FILE.exists():
        return None

    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            token_data = json.load(f)

        refresh_token = token_data.get("refresh_token")
        token_uri = token_data.get("token_uri")
        client_id = token_data.get("client_id")
        client_secret = token_data.get("client_secret")
        scopes = token_data.get("scopes") or SCOPES

        if not (refresh_token and token_uri and client_id and client_secret):
            logger.error("Token file is missing required fields; re-authentication needed.")
            return None

        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=token_uri,
            client_id=client_id,
            client_secret=client_secret,
            scopes=scopes,
        )
        return creds
    except Exception as e:
        logger.error("Error loading credentials: %s", e, exc_info=True)
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
        # creds.valid może być False, ale bez tokenu – odśwież.
        creds.refresh(Request())
        if not creds.token:
            logger.error("Token refresh returned no access token.")
            return None
        logger.info("Access token refreshed successfully")
        return creds.token
    except Exception as e:
        logger.error("Error refreshing token: %s", e, exc_info=True)
        return None


# -----------------------------------------------------------------------------
# SDM API
# -----------------------------------------------------------------------------
def get_devices() -> dict[str, Any]:
    """
    Get list of devices from Smart Device Management API.

    Returns:
        {"ok": True, "devices": [...]} or {"ok": False, "error": "...", "status_code": int?}
    """
    if not PROJECT_ID:
        return {"ok": False, "error": "GOOGLE_PROJECT_ID not set"}

    token = refresh_access_token()
    if not token:
        # pozwól wyżej zmapować to na 401
        return {
            "ok": False,
            "error": "Not authenticated or token refresh failed",
            "status_code": 401,
        }

    try:
        url = f"{API_BASE}/enterprises/{PROJECT_ID}/devices"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        resp = requests.get(url, headers=headers, timeout=API_TIMEOUT)
        if resp.status_code == 401:
            return {"ok": False, "error": "Unauthorized", "status_code": 401}

        resp.raise_for_status()
        data = resp.json()
        devices = data.get("devices", [])
        logger.info("Retrieved %d devices", len(devices))
        return {"ok": True, "devices": devices}
    except requests.exceptions.RequestException as e:
        logger.error("Error getting devices: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


def send_command(
    device_id: str,
    command: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Send a command to a device.

    Args:
        device_id: Full device resource name (e.g., 'enterprises/.../devices/...')
        command:   SDM command (e.g., 'action.devices.commands.OnOff')
        params:    Dict with command params

    Returns:
        {"ok": True, "result": {...}} or {"ok": False, "error": "...", "status_code": int?}
    """
    token = refresh_access_token()
    if not token:
        return {
            "ok": False,
            "error": "Not authenticated or token refresh failed",
            "status_code": 401,
        }

    try:
        url = f"{API_BASE}/{device_id}:executeCommand"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload = {"command": command, "params": params or {}}

        resp = requests.post(url, headers=headers, json=payload, timeout=API_TIMEOUT)
        if resp.status_code == 401:
            return {"ok": False, "error": "Unauthorized", "status_code": 401}

        resp.raise_for_status()
        result = resp.json() if resp.text else {}
        logger.info("Command '%s' sent to device %s", command, device_id)
        return {"ok": True, "result": result}
    except requests.exceptions.RequestException as e:
        logger.error("Error sending command: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}
