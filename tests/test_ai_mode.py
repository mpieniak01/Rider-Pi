#!/usr/bin/env python3
"""
Unit tests for common.ai_mode module
"""

import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# Import the module under test
from common import ai_mode


class TestAIMode:
    """Test suite for AI mode state management"""

    def setup_method(self):
        """Setup test environment with temporary directories"""
        self.temp_dir = tempfile.mkdtemp()
        self.config_dir = Path(self.temp_dir) / "config"
        self.data_dir = Path(self.temp_dir) / "data"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def teardown_method(self):
        """Cleanup test environment"""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_mode_default(self):
        """Test getting mode returns default when no state exists"""
        with (
            patch.object(ai_mode, "CONFIG_DIR", self.config_dir),
            patch.object(ai_mode, "DATA_DIR", self.data_dir),
            patch.object(ai_mode, "SYSTEM_CONFIG_FILE", self.config_dir / "system.toml"),
            patch.object(ai_mode, "STATE_FILE", self.data_dir / "ai_mode_state.toml"),
        ):
            # Clear any existing state
            state_file = self.data_dir / "ai_mode_state.toml"
            if state_file.exists():
                state_file.unlink()

            mode = ai_mode.get_mode()
            assert mode in ("local", "pc_offload")
            assert mode == "local"  # default

    def test_set_mode_local(self):
        """Test setting mode to local"""
        with (
            patch.object(ai_mode, "CONFIG_DIR", self.config_dir),
            patch.object(ai_mode, "DATA_DIR", self.data_dir),
            patch.object(ai_mode, "SYSTEM_CONFIG_FILE", self.config_dir / "system.toml"),
            patch.object(ai_mode, "STATE_FILE", self.data_dir / "ai_mode_state.toml"),
        ):
            result = ai_mode.set_mode("local")
            assert result["ok"] is True
            assert result["mode"] == "local"
            assert "changed_ts" in result
            assert isinstance(result["changed_ts"], float)

    def test_set_mode_pc_offload(self):
        """Test setting mode to pc_offload"""
        with (
            patch.object(ai_mode, "CONFIG_DIR", self.config_dir),
            patch.object(ai_mode, "DATA_DIR", self.data_dir),
            patch.object(ai_mode, "SYSTEM_CONFIG_FILE", self.config_dir / "system.toml"),
            patch.object(ai_mode, "STATE_FILE", self.data_dir / "ai_mode_state.toml"),
        ):
            result = ai_mode.set_mode("pc_offload")
            assert result["ok"] is True
            assert result["mode"] == "pc_offload"
            assert "changed_ts" in result

    def test_set_mode_invalid(self):
        """Test setting invalid mode raises ValueError"""
        with (
            patch.object(ai_mode, "CONFIG_DIR", self.config_dir),
            patch.object(ai_mode, "DATA_DIR", self.data_dir),
            patch.object(ai_mode, "SYSTEM_CONFIG_FILE", self.config_dir / "system.toml"),
            patch.object(ai_mode, "STATE_FILE", self.data_dir / "ai_mode_state.toml"),
        ):
            with pytest.raises(ValueError) as exc_info:
                ai_mode.set_mode("invalid_mode")  # type: ignore
            assert "Invalid mode" in str(exc_info.value)

    def test_get_mode_info(self):
        """Test getting mode info with timestamp"""
        with (
            patch.object(ai_mode, "CONFIG_DIR", self.config_dir),
            patch.object(ai_mode, "DATA_DIR", self.data_dir),
            patch.object(ai_mode, "SYSTEM_CONFIG_FILE", self.config_dir / "system.toml"),
            patch.object(ai_mode, "STATE_FILE", self.data_dir / "ai_mode_state.toml"),
        ):
            # Set a mode first
            set_result = ai_mode.set_mode("pc_offload")
            set_ts = set_result["changed_ts"]

            # Get mode info
            info = ai_mode.get_mode_info()
            assert info["mode"] == "pc_offload"
            assert info["changed_ts"] == set_ts

    def test_is_offload(self):
        """Test is_offload() helper function"""
        with (
            patch.object(ai_mode, "CONFIG_DIR", self.config_dir),
            patch.object(ai_mode, "DATA_DIR", self.data_dir),
            patch.object(ai_mode, "SYSTEM_CONFIG_FILE", self.config_dir / "system.toml"),
            patch.object(ai_mode, "STATE_FILE", self.data_dir / "ai_mode_state.toml"),
        ):
            # Set to local
            ai_mode.set_mode("local")
            assert ai_mode.is_offload() is False

            # Set to offload
            ai_mode.set_mode("pc_offload")
            assert ai_mode.is_offload() is True

    def test_is_local(self):
        """Test is_local() helper function"""
        with (
            patch.object(ai_mode, "CONFIG_DIR", self.config_dir),
            patch.object(ai_mode, "DATA_DIR", self.data_dir),
            patch.object(ai_mode, "SYSTEM_CONFIG_FILE", self.config_dir / "system.toml"),
            patch.object(ai_mode, "STATE_FILE", self.data_dir / "ai_mode_state.toml"),
        ):
            # Set to local
            ai_mode.set_mode("local")
            assert ai_mode.is_local() is True

            # Set to offload
            ai_mode.set_mode("pc_offload")
            assert ai_mode.is_local() is False

    def test_state_persistence(self):
        """Test that state persists across function calls"""
        with (
            patch.object(ai_mode, "CONFIG_DIR", self.config_dir),
            patch.object(ai_mode, "DATA_DIR", self.data_dir),
            patch.object(ai_mode, "SYSTEM_CONFIG_FILE", self.config_dir / "system.toml"),
            patch.object(ai_mode, "STATE_FILE", self.data_dir / "ai_mode_state.toml"),
        ):
            # Set mode
            ai_mode.set_mode("pc_offload")

            # Read it back
            mode = ai_mode.get_mode()
            assert mode == "pc_offload"

            # Change mode
            ai_mode.set_mode("local")

            # Read it again
            mode = ai_mode.get_mode()
            assert mode == "local"

    def test_mode_change_updates_timestamp(self):
        """Test that changing mode updates the timestamp"""
        with (
            patch.object(ai_mode, "CONFIG_DIR", self.config_dir),
            patch.object(ai_mode, "DATA_DIR", self.data_dir),
            patch.object(ai_mode, "SYSTEM_CONFIG_FILE", self.config_dir / "system.toml"),
            patch.object(ai_mode, "STATE_FILE", self.data_dir / "ai_mode_state.toml"),
        ):
            # Set initial mode
            result1 = ai_mode.set_mode("local")
            ts1 = result1["changed_ts"]

            # Wait a bit
            time.sleep(0.1)

            # Change mode
            result2 = ai_mode.set_mode("pc_offload")
            ts2 = result2["changed_ts"]

            # Timestamp should be different
            assert ts2 > ts1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
