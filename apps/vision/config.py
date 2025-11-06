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
    if os.getenv("SNAP_DIR"):
        edge_preview.snap_dir = os.getenv("SNAP_DIR", edge_preview.snap_dir)
    if os.getenv("EDGE_LOW"):
        edge_preview.edge_low = int(os.getenv("EDGE_LOW", edge_preview.edge_low))
    if os.getenv("EDGE_HIGH"):
        edge_preview.edge_high = int(os.getenv("EDGE_HIGH", edge_preview.edge_high))
    if os.getenv("SNAP_EVERY_MS"):
        edge_preview.snap_every_ms = int(os.getenv("SNAP_EVERY_MS", edge_preview.snap_every_ms))
    if os.getenv("PREVIEW_ROT"):
        edge_preview.preview_rot = int(os.getenv("PREVIEW_ROT", edge_preview.preview_rot))
    if os.getenv("PREVIEW_FLIP_H"):
        edge_preview.preview_flip_h = os.getenv("PREVIEW_FLIP_H") == "1"
    if os.getenv("FRAME_W"):
        edge_preview.frame_w = int(os.getenv("FRAME_W", edge_preview.frame_w))
    if os.getenv("FRAME_H"):
        edge_preview.frame_h = int(os.getenv("FRAME_H", edge_preview.frame_h))
    if os.getenv("LAST_FRAME"):
        edge_preview.last_frame = os.getenv("LAST_FRAME", edge_preview.last_frame)

    # Obstacle legacy mappings
    if os.getenv("PROC_PATH"):
        obstacle.proc_path = os.getenv("PROC_PATH", obstacle.proc_path)
    if os.getenv("RAW_PATH"):
        obstacle.raw_path = os.getenv("RAW_PATH", obstacle.raw_path)
    if os.getenv("DATA_DIR"):
        obstacle.data_dir = os.getenv("DATA_DIR", obstacle.data_dir)
    if os.getenv("OBSTACLE_JSON"):
        obstacle.obstacle_json = os.getenv("OBSTACLE_JSON", obstacle.obstacle_json)
    if os.getenv("ROI_Y0"):
        obstacle.roi_y0 = float(os.getenv("ROI_Y0", obstacle.roi_y0))
    if os.getenv("ROI_H"):
        obstacle.roi_h = float(os.getenv("ROI_H", obstacle.roi_h))
    if os.getenv("EDGE_T_LOW"):
        obstacle.edge_t_low = float(os.getenv("EDGE_T_LOW", obstacle.edge_t_low))
    if os.getenv("EDGE_T_HIGH"):
        obstacle.edge_t_high = float(os.getenv("EDGE_T_HIGH", obstacle.edge_t_high))
    if os.getenv("DARK_LUMA"):
        obstacle.dark_luma = float(os.getenv("DARK_LUMA", obstacle.dark_luma))
    if os.getenv("LAPL_VAR_MIN"):
        obstacle.lapl_var_min = float(os.getenv("LAPL_VAR_MIN", obstacle.lapl_var_min))
    if os.getenv("CONF_GAIN"):
        obstacle.conf_gain = float(os.getenv("CONF_GAIN", obstacle.conf_gain))
    if os.getenv("SNAP_MAX_AGE_S"):
        obstacle.snap_max_age_s = float(os.getenv("SNAP_MAX_AGE_S", obstacle.snap_max_age_s))
    if os.getenv("OBST_DEC_N"):
        obstacle.obst_dec_n = int(os.getenv("OBST_DEC_N", obstacle.obst_dec_n))
    if os.getenv("PUBLISH"):
        obstacle.publish = int(os.getenv("PUBLISH", obstacle.publish))
    if os.getenv("OBST_ANN"):
        obstacle.obst_ann = int(os.getenv("OBST_ANN", obstacle.obst_ann))
    if os.getenv("OBST_ANN_PATH"):
        obstacle.obst_ann_path = os.getenv("OBST_ANN_PATH", obstacle.obst_ann_path)
    if os.getenv("OBST_BINS"):
        obstacle.obst_bins = int(os.getenv("OBST_BINS", obstacle.obst_bins))
    if os.getenv("EDGE_BIN_LOW"):
        obstacle.edge_bin_low = float(os.getenv("EDGE_BIN_LOW", obstacle.edge_bin_low))
    if os.getenv("EDGE_AREA_PCT"):
        obstacle.edge_area_pct = float(os.getenv("EDGE_AREA_PCT", obstacle.edge_area_pct))
    if os.getenv("EDGE_PIX_MIN"):
        obstacle.edge_pix_min = int(os.getenv("EDGE_PIX_MIN", obstacle.edge_pix_min))

    # SSD preview legacy mappings
    if os.getenv("SNAP_DIR") and not os.getenv("SSD_SNAP_DIR"):
        ssd_preview.snap_dir = os.getenv("SNAP_DIR", ssd_preview.snap_dir)
    if os.getenv("PREVIEW_ROT"):
        ssd_preview.preview_rot = int(os.getenv("PREVIEW_ROT", ssd_preview.preview_rot))
    if os.getenv("PREVIEW_FLIP_H"):
        ssd_preview.preview_flip_h = os.getenv("PREVIEW_FLIP_H") == "1"
    if os.getenv("PREVIEW_FLIP_V"):
        ssd_preview.preview_flip_v = os.getenv("PREVIEW_FLIP_V") == "1"
    if os.getenv("DISABLE_LCD"):
        ssd_preview.disable_lcd = os.getenv("DISABLE_LCD") == "1"
    if os.getenv("NO_DRAW"):
        ssd_preview.no_draw = os.getenv("NO_DRAW") == "1"
    if os.getenv("SNAP_EXT"):
        ssd_preview.snap_ext = os.getenv("SNAP_EXT", ssd_preview.snap_ext)
    if os.getenv("DRAW_LATCH_MS"):
        ssd_preview.draw_latch_ms = int(os.getenv("DRAW_LATCH_MS", ssd_preview.draw_latch_ms))
    if os.getenv("SNAP_EVERY_MS"):
        ssd_preview.snap_every_ms = int(os.getenv("SNAP_EVERY_MS", ssd_preview.snap_every_ms))
    if os.getenv("SSD_CLASSES"):
        ssd_preview.ssd_classes = os.getenv("SSD_CLASSES", ssd_preview.ssd_classes)
    if os.getenv("SSD_SCORE"):
        ssd_preview.ssd_score = float(os.getenv("SSD_SCORE", ssd_preview.ssd_score))
    if os.getenv("EVERY") or os.getenv("SSD_EVERY"):
        ssd_preview.ssd_every = int(os.getenv("EVERY", os.getenv("SSD_EVERY", str(ssd_preview.ssd_every))))

    return VisionConfig(
        edge_preview=edge_preview,
        obstacle=obstacle,
        ssd_preview=ssd_preview,
    )
