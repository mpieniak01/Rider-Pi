"""AI Mode Configuration and Management Module.

Provides a global mechanism for switching between local and pc_offload AI processing modes.
This module handles:
- Reading AI mode from environment variable (RIDER_AI_MODE)
- Dynamic mode switching at runtime
- Mode state persistence and querying
"""

from __future__ import annotations

import os
import threading
import time
from typing import Literal

# Valid AI processing modes
AIMode = Literal["local", "pc_offload"]

# Default mode when not specified
DEFAULT_MODE: AIMode = "local"

# Global state for AI mode
_mode_lock = threading.RLock()
_current_mode: AIMode = DEFAULT_MODE
_mode_changed_ts: float = 0.0


def _read_env_mode() -> AIMode:
    """Read AI mode from RIDER_AI_MODE environment variable."""
    env_val = os.getenv("RIDER_AI_MODE", "").strip().lower()
    if env_val in ("local", "pc_offload"):
        return env_val  # type: ignore
    return DEFAULT_MODE


def init_mode() -> AIMode:
    """Initialize AI mode from environment on first import."""
    global _current_mode, _mode_changed_ts
    with _mode_lock:
        _current_mode = _read_env_mode()
        _mode_changed_ts = time.time()
        return _current_mode


def get_mode() -> AIMode:
    """Get current AI processing mode."""
    with _mode_lock:
        return _current_mode


def set_mode(mode: AIMode) -> bool:
    """Set AI processing mode.

    Args:
        mode: New mode to set ("local" or "pc_offload")

    Returns:
        True if mode was changed, False if it was already set
    """
    global _current_mode, _mode_changed_ts

    if mode not in ("local", "pc_offload"):
        raise ValueError(f"Invalid AI mode: {mode}. Must be 'local' or 'pc_offload'")

    with _mode_lock:
        if _current_mode == mode:
            return False
        _current_mode = mode
        _mode_changed_ts = time.time()
        return True


def get_mode_info() -> dict[str, str | float]:
    """Get detailed mode information including timestamp of last change."""
    with _mode_lock:
        return {
            "mode": _current_mode,
            "changed_ts": _mode_changed_ts,
        }


def is_local() -> bool:
    """Check if current mode is local processing."""
    return get_mode() == "local"


def is_offload() -> bool:
    """Check if current mode is PC offload."""
    return get_mode() == "pc_offload"


# Initialize mode on module import
init_mode()
