"""Camera module configuration loader.

Loads configuration from TOML files with ENV override support.
Search order:
  1. CAMERA_CONFIG env var
  2. config/local/camera.toml
  3. config/camera.toml
  4. config/camera.toml.example (fallback)
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
    env_path = os.getenv("CAMERA_CONFIG")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p

    # 2. local/camera.toml
    root = _repo_root()
    local = root / "config" / "local" / "camera.toml"
    if local.exists():
        return local

    # 3. config/camera.toml
    config = root / "config" / "camera.toml"
    if config.exists():
        return config

    # 4. config/camera.toml.example (fallback)
    example = root / "config" / "camera.toml.example"
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
class CameraConfig:
    """Camera module configuration."""

    snap_dir: str = "/home/pi/robot/snapshots"
    raw_path: str = "/home/pi/robot/snapshots/raw.jpg"
    proc_path: str = "/home/pi/robot/snapshots/proc.jpg"
    ssd_path: str = "/home/pi/robot/snapshots/ssd.jpg"
    source: str = "mjpeg"
    preview_rot: int = 270
    preview_flip_h: bool = False
    preview_flip_v: bool = False
    frame_w: int = 640
    frame_h: int = 480


def load_config(path: str | Path | None = None) -> CameraConfig:
    """Load camera configuration from TOML file with ENV overrides.

    Args:
        path: Optional path to config file. If None, uses discovery.

    Returns:
        CameraConfig object with loaded configuration.
    """
    if path is None:
        path = _discover_path()
    else:
        path = Path(path)

    data = _read_toml(path)
    section_data = data.get("camera", {})
    if not isinstance(section_data, dict):
        section_data = {}

    cfg = CameraConfig()

    # Load from TOML
    for key, value in section_data.items():
        if hasattr(cfg, key):
            try:
                setattr(cfg, key, value)
            except (TypeError, ValueError, AttributeError):
                # Skip values that can't be set (wrong type, etc.)
                pass

    # Apply ENV overrides (ENV > TOML > defaults)
    # Legacy ENV names have priority for backwards compatibility
    snap_dir_env = os.getenv("SNAP_DIR")
    if snap_dir_env:
        cfg.snap_dir = snap_dir_env

    raw_path_env = os.getenv("RAW_PATH")
    if raw_path_env:
        cfg.raw_path = raw_path_env

    proc_path_env = os.getenv("PROC_PATH")
    if proc_path_env:
        cfg.proc_path = proc_path_env

    ssd_path_env = os.getenv("SSD_PATH")
    if ssd_path_env:
        cfg.ssd_path = ssd_path_env

    source_env = os.getenv("CAMERA_SOURCE")
    if source_env:
        cfg.source = source_env

    preview_rot_env = os.getenv("PREVIEW_ROT")
    if preview_rot_env:
        cfg.preview_rot = int(preview_rot_env)

    preview_flip_h_env = os.getenv("PREVIEW_FLIP_H")
    if preview_flip_h_env:
        cfg.preview_flip_h = preview_flip_h_env == "1"

    preview_flip_v_env = os.getenv("PREVIEW_FLIP_V")
    if preview_flip_v_env:
        cfg.preview_flip_v = preview_flip_v_env == "1"

    frame_w_env = os.getenv("FRAME_W")
    if frame_w_env:
        cfg.frame_w = int(frame_w_env)

    frame_h_env = os.getenv("FRAME_H")
    if frame_h_env:
        cfg.frame_h = int(frame_h_env)

    return cfg
