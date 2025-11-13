#!/usr/bin/env python3
"""
AI Mode State Management Module

Manages the AI processing mode for the robot:
- "local": All AI processing (Vision, Voice, NLU) runs locally on Raspberry Pi
- "pc_offload": Heavy AI processing is offloaded to a more powerful PC via ZMQ

State is persisted to disk and can be queried/changed at runtime without
requiring service restarts.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Literal

try:
    import tomli as tomllib  # type: ignore
except ImportError:
    import tomllib  # type: ignore (Python 3.11+)

try:
    import tomli_w  # type: ignore
except ImportError:
    tomli_w = None  # type: ignore

# Type alias for AI modes
AIMode = Literal["local", "pc_offload"]

# Default configuration
DEFAULT_MODE: AIMode = "local"

# Configuration paths
CONFIG_DIR = Path(os.getenv("CONFIG_DIR", Path.home() / "robot" / "config"))
SYSTEM_CONFIG_FILE = CONFIG_DIR / "system.toml"
DATA_DIR = Path(os.getenv("DATA_DIR", Path.home() / "robot" / "data"))
STATE_FILE = DATA_DIR / "ai_mode_state.toml"


def _ensure_dirs() -> None:
    """Ensure configuration and data directories exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_default_mode() -> AIMode:
    """Load default mode from system.toml configuration file."""
    if not SYSTEM_CONFIG_FILE.exists():
        return DEFAULT_MODE

    try:
        with SYSTEM_CONFIG_FILE.open("rb") as f:
            config = tomllib.load(f)
        mode_str = config.get("ai", {}).get("default_mode", DEFAULT_MODE)
        if mode_str in ("local", "pc_offload"):
            return mode_str  # type: ignore
        return DEFAULT_MODE
    except Exception:
        return DEFAULT_MODE


def _load_state() -> dict:
    """Load current state from state file."""
    if not STATE_FILE.exists():
        return {}

    try:
        with STATE_FILE.open("rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    """Save state to state file."""
    if tomli_w is None:
        # Fallback: write manually formatted TOML
        _ensure_dirs()
        with STATE_FILE.open("w") as f:
            f.write("# AI Mode State\n")
            f.write(f'mode = "{state.get("mode", DEFAULT_MODE)}"\n')
            f.write(f'changed_ts = {state.get("changed_ts", time.time())}\n')
        return

    _ensure_dirs()
    with STATE_FILE.open("wb") as f:
        tomli_w.dump(state, f)


def get_mode() -> AIMode:
    """
    Get the current AI processing mode.

    Returns:
        Current mode: "local" or "pc_offload"
    """
    state = _load_state()
    mode = state.get("mode")

    # If no saved state, use default from config
    if mode not in ("local", "pc_offload"):
        mode = _load_default_mode()

    return mode  # type: ignore


def set_mode(mode: AIMode) -> dict:
    """
    Set the AI processing mode.

    Args:
        mode: New mode ("local" or "pc_offload")

    Returns:
        Dictionary with result status: {"ok": bool, "mode": str, "changed_ts": float}

    Raises:
        ValueError: If mode is not valid
    """
    if mode not in ("local", "pc_offload"):
        raise ValueError(f"Invalid mode: {mode}. Must be 'local' or 'pc_offload'")

    changed_ts = time.time()
    state = {"mode": mode, "changed_ts": changed_ts}
    _save_state(state)

    return {"ok": True, "mode": mode, "changed_ts": changed_ts}


def get_mode_info() -> dict:
    """
    Get current mode information including timestamp of last change.

    Returns:
        Dictionary with: {"mode": str, "changed_ts": float}
    """
    state = _load_state()
    mode = state.get("mode")

    if mode not in ("local", "pc_offload"):
        mode = _load_default_mode()

    changed_ts = state.get("changed_ts", 0.0)

    return {"mode": mode, "changed_ts": changed_ts}


def is_offload() -> bool:
    """
    Check if currently in PC offload mode.

    Returns:
        True if mode is "pc_offload", False otherwise
    """
    return get_mode() == "pc_offload"


def is_local() -> bool:
    """
    Check if currently in local mode.

    Returns:
        True if mode is "local", False otherwise
    """
    return get_mode() == "local"


# Initialize state file with default if it doesn't exist
def _initialize_if_needed() -> None:
    """Initialize state file with default mode if it doesn't exist."""
    if not STATE_FILE.exists():
        default_mode = _load_default_mode()
        _save_state({"mode": default_mode, "changed_ts": time.time()})


# Auto-initialize on import
_initialize_if_needed()
