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
    bus_sub_port_env = os.getenv("BUS_SUB_PORT")
    if bus_sub_port_env:
        cfg.bus_sub_port = int(bus_sub_port_env)

    kp_env = os.getenv("TRACKING_KP")
    if kp_env:
        cfg.kp = float(kp_env)

    dead_zone_env = os.getenv("TRACKING_DEAD_ZONE")
    if dead_zone_env:
        cfg.dead_zone = float(dead_zone_env)

    timeout_env = os.getenv("TRACKING_TIMEOUT")
    if timeout_env:
        cfg.timeout_s = float(timeout_env)

    max_speed_env = os.getenv("TRACKING_MAX_SPEED")
    if max_speed_env:
        cfg.max_speed = float(max_speed_env)

    cmd_duration_env = os.getenv("TRACKING_CMD_DURATION")
    if cmd_duration_env:
        cfg.cmd_duration = float(cmd_duration_env)

    cmd_prio_env = os.getenv("TRACKING_CMD_PRIO")
    if cmd_prio_env:
        cfg.cmd_prio = int(cmd_prio_env)

    log_level_env = os.getenv("TRACKING_LOG_LEVEL")
    if log_level_env:
        cfg.log_level = log_level_env

    return cfg
