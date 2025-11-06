"""Google Bridge module configuration loader.

Loads configuration from TOML files with ENV override support.
Search order:
  1. GOOGLE_BRIDGE_CONFIG env var
  2. config/local/google_bridge.toml
  3. config/google_bridge.toml
  4. config/google_bridge.toml.example (fallback)
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
    env_path = os.getenv("GOOGLE_BRIDGE_CONFIG")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p

    # 2. local/google_bridge.toml
    root = _repo_root()
    local = root / "config" / "local" / "google_bridge.toml"
    if local.exists():
        return local

    # 3. config/google_bridge.toml
    config = root / "config" / "google_bridge.toml"
    if config.exists():
        return config

    # 4. config/google_bridge.toml.example (fallback)
    example = root / "config" / "google_bridge.toml.example"
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
class GoogleBridgeConfig:
    """Google Bridge service configuration."""

    enabled: bool = True
    poll_interval_s: int = 300
    data_dir: str = "/home/pi/robot/data"
    google_data_dir: str = "google"
    status_file: str = "status.json"
    last_file: str = "last.json"
    log_level: str = "INFO"


def load_config(path: str | Path | None = None) -> GoogleBridgeConfig:
    """Load google_bridge configuration from TOML file with ENV overrides.

    Args:
        path: Optional path to config file. If None, uses discovery.

    Returns:
        GoogleBridgeConfig object with loaded configuration.
    """
    if path is None:
        path = _discover_path()
    else:
        path = Path(path)

    data = _read_toml(path)
    section_data = data.get("google_bridge", {})
    if not isinstance(section_data, dict):
        section_data = {}

    cfg = GoogleBridgeConfig()

    # Load from TOML
    for key, value in section_data.items():
        if hasattr(cfg, key):
            try:
                setattr(cfg, key, value)
            except Exception:
                pass

    # Apply ENV overrides (ENV > TOML > defaults)
    # Legacy ENV names have priority for backwards compatibility
    if os.getenv("GOOGLE_ENABLED"):
        cfg.enabled = os.getenv("GOOGLE_ENABLED") == "1"
    if os.getenv("GOOGLE_POLL_S"):
        cfg.poll_interval_s = int(os.getenv("GOOGLE_POLL_S", cfg.poll_interval_s))
    if os.getenv("DATA_DIR"):
        cfg.data_dir = os.getenv("DATA_DIR", cfg.data_dir)
    if os.getenv("GOOGLE_DATA_DIR"):
        cfg.google_data_dir = os.getenv("GOOGLE_DATA_DIR", cfg.google_data_dir)
    if os.getenv("GOOGLE_BRIDGE_LOG_LEVEL"):
        cfg.log_level = os.getenv("GOOGLE_BRIDGE_LOG_LEVEL", cfg.log_level)

    return cfg
