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
        from common import ai_mode

        # Test initial mode (should be default)
        mode = ai_mode.get_mode()
        assert mode in ("local", "pc_offload")

        # Test set_mode to local
        changed = ai_mode.set_mode("local")
        # changed can be True or False depending on initial state
        assert ai_mode.get_mode() == "local"

        # Test set_mode to pc_offload
        changed = ai_mode.set_mode("pc_offload")
        assert changed is True  # Should have changed
        assert ai_mode.get_mode() == "pc_offload"

        # Test setting same mode again
        changed = ai_mode.set_mode("pc_offload")
        assert changed is False  # Should not have changed
        assert ai_mode.get_mode() == "pc_offload"

    def test_ai_mode_api_handlers_directly(self, temp_dirs):
        """Test API handler functions directly (no Flask client)"""
        from common import ai_mode

        # Initialize mode
        ai_mode.set_mode("local")

        # Test get_mode_info
        info = ai_mode.get_mode_info()
        assert info["mode"] == "local"
        assert "changed_ts" in info

        # Test set_mode
        changed = ai_mode.set_mode("pc_offload")
        assert changed is True
        assert ai_mode.get_mode() == "pc_offload"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
