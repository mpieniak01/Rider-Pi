"""Motion module configuration loader.

Loads configuration from TOML files with ENV override support.
Search order:
  1. MOTION_CONFIG env var
  2. config/local/motion.toml
  3. config/motion.toml
  4. config/motion.toml.example (fallback)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib  # type: ignore[attr-defined]
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # type: ignore


def _repo_root() -> Path:
    """Get repository root directory."""
    return Path(__file__).resolve().parents[2]


def _discover_path() -> Path:
    """Discover configuration file path."""
    # 1. ENV override
    env_path = os.getenv("MOTION_CONFIG")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p

    # 2. local/motion.toml
    root = _repo_root()
    local = root / "config" / "local" / "motion.toml"
    if local.exists():
        return local

    # 3. config/motion.toml
    config = root / "config" / "motion.toml"
    if config.exists():
        return config

    # 4. config/motion.toml.example (fallback)
    example = root / "config" / "motion.toml.example"
    if example.exists():
        return example

    # Return config path even if it doesn't exist (will return empty dict)
    return config


def _read_toml(path: Path) -> dict[str, Any]:
    """Read TOML file and return parsed data."""
    if tomllib is None or not path.exists():
        return {}
    try:
        with path.open("rb") as f:
            return tomllib.load(f) or {}
    except Exception:
        return {}


@dataclass
class TrackingConfig:
    """Tracking controller configuration."""

    bus_sub_port: int = 5556
    kp: float = 0.15
    dead_zone: float = 0.10
    timeout_s: float = 1.0
    max_speed: float = 0.20
    cmd_duration: float = 0.20
    cmd_prio: int = 50
    log_level: str = "INFO"


def load_config(path: str | Path | None = None) -> TrackingConfig:
    """Load motion configuration from TOML file with ENV overrides.

    Args:
        path: Optional path to config file. If None, uses discovery.

    Returns:
        TrackingConfig object with loaded configuration.
    """
    if path is None:
        path = _discover_path()
    else:
        path = Path(path)

    data = _read_toml(path)
    section_data = data.get("tracking", {})
    if not isinstance(section_data, dict):
        section_data = {}

    cfg = TrackingConfig()

    # Load from TOML
    for key, value in section_data.items():
        if hasattr(cfg, key):
            try:
                setattr(cfg, key, value)
            except Exception:
                pass

    # Apply ENV overrides (ENV > TOML > defaults)
    # Legacy ENV names have priority for backwards compatibility
    if os.getenv("BUS_SUB_PORT"):
        cfg.bus_sub_port = int(os.getenv("BUS_SUB_PORT", cfg.bus_sub_port))
    if os.getenv("TRACKING_KP"):
        cfg.kp = float(os.getenv("TRACKING_KP", cfg.kp))
    if os.getenv("TRACKING_DEAD_ZONE"):
        cfg.dead_zone = float(os.getenv("TRACKING_DEAD_ZONE", cfg.dead_zone))
    if os.getenv("TRACKING_TIMEOUT"):
        cfg.timeout_s = float(os.getenv("TRACKING_TIMEOUT", cfg.timeout_s))
    if os.getenv("TRACKING_MAX_SPEED"):
        cfg.max_speed = float(os.getenv("TRACKING_MAX_SPEED", cfg.max_speed))
    if os.getenv("TRACKING_CMD_DURATION"):
        cfg.cmd_duration = float(os.getenv("TRACKING_CMD_DURATION", cfg.cmd_duration))
    if os.getenv("TRACKING_CMD_PRIO"):
        cfg.cmd_prio = int(os.getenv("TRACKING_CMD_PRIO", cfg.cmd_prio))
    if os.getenv("TRACKING_LOG_LEVEL"):
        cfg.log_level = os.getenv("TRACKING_LOG_LEVEL", cfg.log_level)

    return cfg
