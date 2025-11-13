#!/usr/bin/env python3
"""
Unit tests for AI mode API endpoints
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestAIModeAPI:
    """Test suite for AI mode API endpoints"""

    @pytest.fixture
    def client(self):
        """Create a test client"""
        # Import here to avoid issues with missing dependencies
        from services.api_server import app

        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories for testing"""
        temp_dir = tempfile.mkdtemp()
        config_dir = Path(temp_dir) / "config"
        data_dir = Path(temp_dir) / "data"
        config_dir.mkdir(parents=True, exist_ok=True)
        data_dir.mkdir(parents=True, exist_ok=True)
        yield config_dir, data_dir
        import shutil

        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_ai_mode_module_functions(self, temp_dirs):
        """Test AI mode module functions directly (no Flask)"""
        config_dir, data_dir = temp_dirs
        with (
            patch("common.ai_mode.CONFIG_DIR", config_dir),
            patch("common.ai_mode.DATA_DIR", data_dir),
            patch("common.ai_mode.SYSTEM_CONFIG_FILE", config_dir / "system.toml"),
            patch("common.ai_mode.STATE_FILE", data_dir / "ai_mode_state.toml"),
        ):
            from common import ai_mode

            # Test set and get
            result = ai_mode.set_mode("local")
            assert result["ok"] is True
            assert result["mode"] == "local"

            mode = ai_mode.get_mode()
            assert mode == "local"

            # Test change
            result = ai_mode.set_mode("pc_offload")
            assert result["ok"] is True
            assert result["mode"] == "pc_offload"

            mode = ai_mode.get_mode()
            assert mode == "pc_offload"

    def test_ai_mode_api_handlers_directly(self, temp_dirs):
        """Test API handler functions directly (no Flask client)"""
        config_dir, data_dir = temp_dirs
        with (
            patch("common.ai_mode.CONFIG_DIR", config_dir),
            patch("common.ai_mode.DATA_DIR", data_dir),
            patch("common.ai_mode.SYSTEM_CONFIG_FILE", config_dir / "system.toml"),
            patch("common.ai_mode.STATE_FILE", data_dir / "ai_mode_state.toml"),
            patch("services.api_core.compat.bus_pub"),
        ):
            from common import ai_mode

            # Initialize mode
            ai_mode.set_mode("local")

            # Test get_mode_info
            info = ai_mode.get_mode_info()
            assert info["mode"] == "local"
            assert "changed_ts" in info

            # Test set_mode with ZMQ event
            result = ai_mode.set_mode("pc_offload")
            assert result["ok"] is True
            assert result["mode"] == "pc_offload"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

