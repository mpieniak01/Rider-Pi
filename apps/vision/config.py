"""Vision module configuration loader.

Loads configuration from TOML files with ENV override support.
Search order:
  1. VISION_CONFIG env var
  2. config/local/vision.toml
  3. config/vision.toml
  4. config/vision.toml.example (fallback)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
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
    env_path = os.getenv("VISION_CONFIG")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p

    # 2. local/vision.toml
    root = _repo_root()
    local = root / "config" / "local" / "vision.toml"
    if local.exists():
        return local

    # 3. config/vision.toml
    config = root / "config" / "vision.toml"
    if config.exists():
        return config

    # 4. config/vision.toml.example (fallback)
    example = root / "config" / "vision.toml.example"
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
class EdgePreviewConfig:
    """Edge preview service configuration."""

    snap_dir: str = "/home/pi/robot/snapshots"
    edge_low: int = 60
    edge_high: int = 120
    snap_every_ms: int = 500
    preview_rot: int = 0
    preview_flip_h: bool = False
    frame_w: int = 640
    frame_h: int = 480
    last_frame: str = "/home/pi/robot/data/last_frame.jpg"


@dataclass
class ObstacleConfig:
    """Obstacle detection service configuration."""

    proc_path: str = "/home/pi/robot/snapshots/proc.jpg"
    raw_path: str = "/home/pi/robot/snapshots/raw.jpg"
    data_dir: str = "/home/pi/robot/data"
    obstacle_json: str = "/home/pi/robot/data/obstacle.json"
    roi_y0: float = 0.55
    roi_h: float = 0.40
    edge_t_low: float = 0.10
    edge_t_high: float = 0.18
    dark_luma: float = 0.15
    lapl_var_min: float = 30.0
    conf_gain: float = 4.0
    snap_max_age_s: float = 3.0
    obst_dec_n: int = 3
    publish: int = 0
    obst_ann: int = 0
    obst_ann_path: str = "/home/pi/robot/snapshots/obst_annot.jpg"
    obst_bins: int = 24
    edge_bin_low: float = 0.06
    edge_area_pct: float = 0.18
    edge_pix_min: int = 16000


@dataclass
class SSDPreviewConfig:
    """SSD preview service configuration."""

    snap_dir: str = "/home/pi/robot/snapshots"
    preview_rot: int = 270
    preview_flip_h: bool = False
    preview_flip_v: bool = False
    disable_lcd: bool = False
    no_draw: bool = False
    snap_ext: str = ""
    draw_latch_ms: int = 700
    snap_every_ms: int = 500
    ssd_classes: str = "person"
    ssd_score: float = 0.55
    ssd_every: int = 1


@dataclass
class VisionConfig:
    """Complete vision module configuration."""

    edge_preview: EdgePreviewConfig = field(default_factory=EdgePreviewConfig)
    obstacle: ObstacleConfig = field(default_factory=ObstacleConfig)
    ssd_preview: SSDPreviewConfig = field(default_factory=SSDPreviewConfig)


def _load_section(data: dict[str, Any], section: str, config_cls: type) -> Any:
    """Load a configuration section from TOML data."""
    section_data = data.get(section, {})
    if not isinstance(section_data, dict):
        section_data = {}

    cfg = config_cls()
    for key, value in section_data.items():
        if hasattr(cfg, key):
            try:
                setattr(cfg, key, value)
            except Exception:
                pass
    return cfg


def _apply_env_overrides(cfg: Any, prefix: str) -> None:
    """Apply environment variable overrides to config object."""
    for field_name in dir(cfg):
        if field_name.startswith("_"):
            continue
        env_key = f"{prefix}_{field_name}".upper()
        env_val = os.getenv(env_key)
        if env_val is None:
            continue

        try:
            field_val = getattr(cfg, field_name)
            if isinstance(field_val, bool):
                setattr(cfg, field_name, env_val.lower() not in {"0", "false", "no", ""})
            elif isinstance(field_val, int):
                setattr(cfg, field_name, int(env_val))
            elif isinstance(field_val, float):
                setattr(cfg, field_name, float(env_val))
            elif isinstance(field_val, str):
                setattr(cfg, field_name, env_val)
        except Exception:
            pass


def load_config(path: str | Path | None = None) -> VisionConfig:
    """Load vision configuration from TOML file with ENV overrides.

    Args:
        path: Optional path to config file. If None, uses discovery.

    Returns:
        VisionConfig object with loaded configuration.
    """
    if path is None:
        path = _discover_path()
    else:
        path = Path(path)

    data = _read_toml(path)

    # Load each section
    edge_preview = _load_section(data, "edge_preview", EdgePreviewConfig)
    obstacle = _load_section(data, "obstacle", ObstacleConfig)
    ssd_preview = _load_section(data, "ssd_preview", SSDPreviewConfig)

    # Apply ENV overrides (ENV > TOML > defaults)
    _apply_env_overrides(edge_preview, "EDGE")
    _apply_env_overrides(obstacle, "OBST")
    _apply_env_overrides(ssd_preview, "SSD")

    # Also check for legacy ENV names used in original code
    # EdgePreview legacy mappings
    snap_dir_env = os.getenv("SNAP_DIR")
    if snap_dir_env:
        edge_preview.snap_dir = snap_dir_env

    edge_low_env = os.getenv("EDGE_LOW")
    if edge_low_env:
        edge_preview.edge_low = int(edge_low_env)

    edge_high_env = os.getenv("EDGE_HIGH")
    if edge_high_env:
        edge_preview.edge_high = int(edge_high_env)

    snap_every_env = os.getenv("SNAP_EVERY_MS")
    if snap_every_env:
        edge_preview.snap_every_ms = int(snap_every_env)

    preview_rot_env = os.getenv("PREVIEW_ROT")
    if preview_rot_env:
        edge_preview.preview_rot = int(preview_rot_env)

    preview_flip_h_env = os.getenv("PREVIEW_FLIP_H")
    if preview_flip_h_env:
        edge_preview.preview_flip_h = preview_flip_h_env == "1"

    frame_w_env = os.getenv("FRAME_W")
    if frame_w_env:
        edge_preview.frame_w = int(frame_w_env)

    frame_h_env = os.getenv("FRAME_H")
    if frame_h_env:
        edge_preview.frame_h = int(frame_h_env)

    last_frame_env = os.getenv("LAST_FRAME")
    if last_frame_env:
        edge_preview.last_frame = last_frame_env

    # Obstacle legacy mappings
    proc_path_env = os.getenv("PROC_PATH")
    if proc_path_env:
        obstacle.proc_path = proc_path_env

    raw_path_env = os.getenv("RAW_PATH")
    if raw_path_env:
        obstacle.raw_path = raw_path_env

    data_dir_env = os.getenv("DATA_DIR")
    if data_dir_env:
        obstacle.data_dir = data_dir_env

    obstacle_json_env = os.getenv("OBSTACLE_JSON")
    if obstacle_json_env:
        obstacle.obstacle_json = obstacle_json_env

    roi_y0_env = os.getenv("ROI_Y0")
    if roi_y0_env:
        obstacle.roi_y0 = float(roi_y0_env)

    roi_h_env = os.getenv("ROI_H")
    if roi_h_env:
        obstacle.roi_h = float(roi_h_env)

    edge_t_low_env = os.getenv("EDGE_T_LOW")
    if edge_t_low_env:
        obstacle.edge_t_low = float(edge_t_low_env)

    edge_t_high_env = os.getenv("EDGE_T_HIGH")
    if edge_t_high_env:
        obstacle.edge_t_high = float(edge_t_high_env)

    dark_luma_env = os.getenv("DARK_LUMA")
    if dark_luma_env:
        obstacle.dark_luma = float(dark_luma_env)

    lapl_var_min_env = os.getenv("LAPL_VAR_MIN")
    if lapl_var_min_env:
        obstacle.lapl_var_min = float(lapl_var_min_env)

    conf_gain_env = os.getenv("CONF_GAIN")
    if conf_gain_env:
        obstacle.conf_gain = float(conf_gain_env)

    snap_max_age_env = os.getenv("SNAP_MAX_AGE_S")
    if snap_max_age_env:
        obstacle.snap_max_age_s = float(snap_max_age_env)

    obst_dec_n_env = os.getenv("OBST_DEC_N")
    if obst_dec_n_env:
        obstacle.obst_dec_n = int(obst_dec_n_env)

    publish_env = os.getenv("PUBLISH")
    if publish_env:
        obstacle.publish = int(publish_env)

    obst_ann_env = os.getenv("OBST_ANN")
    if obst_ann_env:
        obstacle.obst_ann = int(obst_ann_env)

    obst_ann_path_env = os.getenv("OBST_ANN_PATH")
    if obst_ann_path_env:
        obstacle.obst_ann_path = obst_ann_path_env

    obst_bins_env = os.getenv("OBST_BINS")
    if obst_bins_env:
        obstacle.obst_bins = int(obst_bins_env)

    edge_bin_low_env = os.getenv("EDGE_BIN_LOW")
    if edge_bin_low_env:
        obstacle.edge_bin_low = float(edge_bin_low_env)

    edge_area_pct_env = os.getenv("EDGE_AREA_PCT")
    if edge_area_pct_env:
        obstacle.edge_area_pct = float(edge_area_pct_env)

    edge_pix_min_env = os.getenv("EDGE_PIX_MIN")
    if edge_pix_min_env:
        obstacle.edge_pix_min = int(edge_pix_min_env)

    # SSD preview legacy mappings
    # Note: SNAP_DIR is shared between edge_preview and ssd_preview
    # SSD_SNAP_DIR takes priority, otherwise falls back to SNAP_DIR
    ssd_snap_dir_env = os.getenv("SSD_SNAP_DIR") or os.getenv("SNAP_DIR")
    if ssd_snap_dir_env:
        ssd_preview.snap_dir = ssd_snap_dir_env

    # PREVIEW_ROT is shared across modules
    if preview_rot_env:
        ssd_preview.preview_rot = int(preview_rot_env)

    preview_flip_v_env = os.getenv("PREVIEW_FLIP_V")
    if preview_flip_v_env:
        ssd_preview.preview_flip_v = preview_flip_v_env == "1"

    if preview_flip_h_env:
        ssd_preview.preview_flip_h = preview_flip_h_env == "1"

    disable_lcd_env = os.getenv("DISABLE_LCD")
    if disable_lcd_env:
        ssd_preview.disable_lcd = disable_lcd_env == "1"

    no_draw_env = os.getenv("NO_DRAW")
    if no_draw_env:
        ssd_preview.no_draw = no_draw_env == "1"

    snap_ext_env = os.getenv("SNAP_EXT")
    if snap_ext_env:
        ssd_preview.snap_ext = snap_ext_env

    draw_latch_env = os.getenv("DRAW_LATCH_MS")
    if draw_latch_env:
        ssd_preview.draw_latch_ms = int(draw_latch_env)

    snap_every_ssd_env = os.getenv("SNAP_EVERY_MS")
    if snap_every_ssd_env:
        ssd_preview.snap_every_ms = int(snap_every_ssd_env)

    ssd_classes_env = os.getenv("SSD_CLASSES")
    if ssd_classes_env:
        ssd_preview.ssd_classes = ssd_classes_env

    ssd_score_env = os.getenv("SSD_SCORE")
    if ssd_score_env:
        ssd_preview.ssd_score = float(ssd_score_env)

    # Handle EVERY or SSD_EVERY (EVERY has priority for backward compat)
    every_env = os.getenv("EVERY")
    ssd_every_env = os.getenv("SSD_EVERY")
    if every_env:
        ssd_preview.ssd_every = int(every_env)
    elif ssd_every_env:
        ssd_preview.ssd_every = int(ssd_every_env)

    return VisionConfig(
        edge_preview=edge_preview,
        obstacle=obstacle,
        ssd_preview=ssd_preview,
    )
