"""Tests for module configuration loaders.

Tests configuration loading for vision, motion, google_bridge, and camera modules.
Verifies that TOML files are properly loaded with environment variable overrides.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from apps.camera.config import CameraConfig, load_config as load_camera_config
from apps.google_bridge.config import GoogleBridgeConfig, load_config as load_google_bridge_config
from apps.motion.config import TrackingConfig, load_config as load_motion_config
from apps.vision.config import VisionConfig, load_config as load_vision_config


def test_vision_config_loads_from_example():
    """Test that vision config can load from example template."""
    config = load_vision_config()

    assert isinstance(config, VisionConfig)
    assert config.edge_preview is not None
    assert config.obstacle is not None
    assert config.ssd_preview is not None


def test_vision_config_edge_preview_defaults():
    """Test vision edge preview configuration defaults."""
    config = load_vision_config()

    # Check edge preview defaults
    assert config.edge_preview.snap_dir == "/home/pi/robot/snapshots"
    assert config.edge_preview.edge_low == 60
    assert config.edge_preview.edge_high == 120
    assert config.edge_preview.snap_every_ms == 500
    assert config.edge_preview.frame_w == 640
    assert config.edge_preview.frame_h == 480


def test_vision_config_obstacle_defaults():
    """Test vision obstacle configuration defaults."""
    config = load_vision_config()

    # Check obstacle defaults
    assert config.obstacle.roi_y0 == 0.55
    assert config.obstacle.roi_h == 0.40
    assert config.obstacle.edge_t_low == 0.10
    assert config.obstacle.edge_t_high == 0.18
    assert config.obstacle.dark_luma == 0.15
    assert config.obstacle.lapl_var_min == 30.0


def test_vision_config_env_override():
    """Test that environment variables override TOML config."""
    with mock.patch.dict(
        os.environ,
        {
            "SNAP_DIR": "/custom/snap/dir",
            "EDGE_LOW": "100",
            "ROI_Y0": "0.6",
        },
    ):
        config = load_vision_config()

        # ENV overrides should apply
        assert config.edge_preview.snap_dir == "/custom/snap/dir"
        assert config.edge_preview.edge_low == 100
        assert config.obstacle.roi_y0 == 0.6


def test_google_bridge_config_loads_from_example():
    """Test that google_bridge config can load from example template."""
    config = load_google_bridge_config()

    assert isinstance(config, GoogleBridgeConfig)
    assert config.enabled is True
    assert config.poll_interval_s == 300
    assert config.data_dir == "/home/pi/robot/data"
    assert config.google_data_dir == "google"


def test_google_bridge_config_env_override():
    """Test that environment variables override TOML config."""
    with mock.patch.dict(
        os.environ,
        {
            "GOOGLE_ENABLED": "0",
            "GOOGLE_POLL_S": "600",
            "DATA_DIR": "/custom/data",
        },
    ):
        config = load_google_bridge_config()

        # ENV overrides should apply
        assert config.enabled is False
        assert config.poll_interval_s == 600
        assert config.data_dir == "/custom/data"


def test_motion_config_loads_from_example():
    """Test that motion config can load from example template."""
    config = load_motion_config()

    assert isinstance(config, TrackingConfig)
    assert config.bus_sub_port == 5556
    assert config.kp == 0.15
    assert config.dead_zone == 0.10
    assert config.timeout_s == 1.0
    assert config.max_speed == 0.20
    assert config.cmd_duration == 0.20
    assert config.cmd_prio == 50


def test_motion_config_env_override():
    """Test that environment variables override TOML config for motion."""
    with mock.patch.dict(
        os.environ,
        {
            "TRACKING_KP": "0.25",
            "TRACKING_DEAD_ZONE": "0.15",
            "TRACKING_TIMEOUT": "2.0",
        },
    ):
        config = load_motion_config()

        # ENV overrides should apply
        assert config.kp == 0.25
        assert config.dead_zone == 0.15
        assert config.timeout_s == 2.0


def test_camera_config_loads_from_example():
    """Test that camera config can load from example template."""
    config = load_camera_config()

    assert isinstance(config, CameraConfig)
    assert config.snap_dir == "/home/pi/robot/snapshots"
    assert config.preview_rot == 270
    assert config.preview_flip_h is False
    assert config.preview_flip_v is False
    assert config.frame_w == 640
    assert config.frame_h == 480


def test_camera_config_env_override():
    """Test that environment variables override TOML config for camera."""
    with mock.patch.dict(
        os.environ,
        {
            "SNAP_DIR": "/custom/camera/snaps",
            "PREVIEW_ROT": "90",
            "PREVIEW_FLIP_H": "1",
        },
    ):
        config = load_camera_config()

        # ENV overrides should apply
        assert config.snap_dir == "/custom/camera/snaps"
        assert config.preview_rot == 90
        assert config.preview_flip_h is True


def test_config_from_custom_toml_file():
    """Test loading config from a custom TOML file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)

        # Create a custom vision TOML
        toml_content = """
[edge_preview]
snap_dir = "/test/custom/snaps"
edge_low = 80
edge_high = 160

[obstacle]
roi_y0 = 0.7
roi_h = 0.3
"""
        config_file = tmppath / "custom_vision.toml"
        config_file.write_text(toml_content)

        # Load from custom path
        config = load_vision_config(path=config_file)

        # Custom values should be loaded
        assert config.edge_preview.snap_dir == "/test/custom/snaps"
        assert config.edge_preview.edge_low == 80
        assert config.edge_preview.edge_high == 160
        assert config.obstacle.roi_y0 == 0.7
        assert config.obstacle.roi_h == 0.3


def test_config_with_missing_toml():
    """Test that configs use defaults when TOML file is missing."""
    # Load config from non-existent path
    config = load_vision_config(path="/nonexistent/path.toml")

    # Should fall back to defaults
    assert isinstance(config, VisionConfig)
    assert config.edge_preview.snap_dir == "/home/pi/robot/snapshots"


def test_config_precedence_env_over_toml():
    """Test that ENV variables take precedence over TOML values."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)

        # Create TOML with one value
        toml_content = """
[google_bridge]
poll_interval_s = 300
enabled = true
"""
        config_file = tmppath / "test.toml"
        config_file.write_text(toml_content)

        # Override with ENV
        with mock.patch.dict(
            os.environ,
            {
                "GOOGLE_POLL_S": "900",
                "GOOGLE_ENABLED": "0",
            },
        ):
            config = load_google_bridge_config(path=config_file)

            # ENV should win
            assert config.poll_interval_s == 900
            assert config.enabled is False


def test_motion_config_tracking_params():
    """Test motion tracking controller specific parameters."""
    config = load_motion_config()

    # Verify all tracking-related params are present
    assert hasattr(config, "kp")
    assert hasattr(config, "dead_zone")
    assert hasattr(config, "timeout_s")
    assert hasattr(config, "max_speed")
    assert hasattr(config, "cmd_duration")
    assert hasattr(config, "cmd_prio")
    assert hasattr(config, "log_level")


def test_vision_config_ssd_preview():
    """Test vision SSD preview configuration."""
    config = load_vision_config()

    assert config.ssd_preview.snap_dir == "/home/pi/robot/snapshots"
    assert config.ssd_preview.preview_rot == 270
    assert config.ssd_preview.ssd_classes == "person"
    assert config.ssd_preview.ssd_score == 0.55
    assert config.ssd_preview.draw_latch_ms == 700


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
