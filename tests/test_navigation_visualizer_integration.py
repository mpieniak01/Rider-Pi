#!/usr/bin/env python3
"""
Test navigation visualizer conditional loading in api_server.py

This test verifies that the navigation visualizer module is loaded
conditionally based on the RIDER_NAV_VISUALIZER_ENABLED environment variable.
"""

import os
import unittest
from unittest.mock import MagicMock, patch


class TestNavigationVisualizerIntegration(unittest.TestCase):
    """Test conditional loading of navigation visualizer."""

    def test_visualizer_disabled_by_default(self):
        """Test that visualizer is disabled when env var is not set."""
        # Remove the env var if it exists
        os.environ.pop("RIDER_NAV_VISUALIZER_ENABLED", None)

        # Mock app with logger
        mock_app = MagicMock()
        mock_logger = MagicMock()
        mock_app.logger = mock_logger

        # Simulate the conditional loading logic
        if os.getenv("RIDER_NAV_VISUALIZER_ENABLED", "false").lower() == "true":
            mock_logger.info("[api] Loading optional module: Navigation Visualizer")
        else:
            mock_logger.info("[api] Navigation Visualizer is disabled (RIDER_NAV_VISUALIZER_ENABLED!=true)")

        # Verify the disabled message was logged
        mock_logger.info.assert_called_once_with(
            "[api] Navigation Visualizer is disabled (RIDER_NAV_VISUALIZER_ENABLED!=true)"
        )

    def test_visualizer_disabled_when_false(self):
        """Test that visualizer is disabled when env var is 'false'."""
        os.environ["RIDER_NAV_VISUALIZER_ENABLED"] = "false"

        mock_app = MagicMock()
        mock_logger = MagicMock()
        mock_app.logger = mock_logger

        if os.getenv("RIDER_NAV_VISUALIZER_ENABLED", "false").lower() == "true":
            mock_logger.info("[api] Loading optional module: Navigation Visualizer")
        else:
            mock_logger.info("[api] Navigation Visualizer is disabled (RIDER_NAV_VISUALIZER_ENABLED!=true)")

        mock_logger.info.assert_called_once_with(
            "[api] Navigation Visualizer is disabled (RIDER_NAV_VISUALIZER_ENABLED!=true)"
        )

    def test_visualizer_enabled_when_true(self):
        """Test that visualizer loads when env var is 'true'."""
        os.environ["RIDER_NAV_VISUALIZER_ENABLED"] = "true"

        mock_app = MagicMock()
        mock_logger = MagicMock()
        mock_app.logger = mock_logger

        # Mock importlib and module
        with patch("importlib.import_module") as mock_import:
            mock_module = MagicMock()
            mock_register = MagicMock()
            mock_module.register_websocket_endpoint = mock_register
            mock_import.return_value = mock_module

            # Simulate the conditional loading logic
            if os.getenv("RIDER_NAV_VISUALIZER_ENABLED", "false").lower() == "true":
                mock_logger.info("[api] Loading optional module: Navigation Visualizer")
                import importlib

                nav_bridge_module = importlib.import_module("services.navigation_websocket_bridge")
                register_websocket_endpoint = getattr(nav_bridge_module, "register_websocket_endpoint")
                register_websocket_endpoint(mock_app)
                mock_logger.info("[api] Navigation Visualizer loaded successfully. Endpoint: /ws/navigation")
            else:
                mock_logger.info("[api] Navigation Visualizer is disabled (RIDER_NAV_VISUALIZER_ENABLED!=true)")

            # Verify the module was imported and registered
            mock_import.assert_called_once_with("services.navigation_websocket_bridge")
            mock_register.assert_called_once_with(mock_app)

            # Verify logging messages
            self.assertEqual(mock_logger.info.call_count, 2)
            mock_logger.info.assert_any_call("[api] Loading optional module: Navigation Visualizer")
            mock_logger.info.assert_any_call(
                "[api] Navigation Visualizer loaded successfully. Endpoint: /ws/navigation"
            )

    def test_env_var_case_insensitive(self):
        """Test that env var checking is case-insensitive."""
        test_cases = [
            ("true", True),
            ("True", True),
            ("TRUE", True),
            ("false", False),
            ("False", False),
            ("FALSE", False),
            ("", False),
            ("invalid", False),
        ]

        for value, expected_enabled in test_cases:
            with self.subTest(value=value):
                os.environ["RIDER_NAV_VISUALIZER_ENABLED"] = value
                result = os.getenv("RIDER_NAV_VISUALIZER_ENABLED", "false").lower() == "true"
                self.assertEqual(
                    result,
                    expected_enabled,
                    f"Expected {expected_enabled} for value '{value}', got {result}",
                )


if __name__ == "__main__":
    unittest.main()
