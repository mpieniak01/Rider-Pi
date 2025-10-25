#!/usr/bin/env python3
"""
Basic tests for Google Home API integration.
Tests core functionality without requiring actual Google credentials.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import the module we're testing
import services.api_core.google_home_api as gha


class TestGoogleHomeAPI:
    """Test suite for Google Home API module."""

    def test_module_constants(self):
        """Test that module constants are properly defined."""
        assert isinstance(gha.SCOPES, list)
        assert len(gha.SCOPES) > 0
        assert "sdm.service" in gha.SCOPES[0]
        assert gha.API_BASE.startswith("https://")

    def test_is_authenticated_no_token_file(self):
        """Test is_authenticated returns False when token file doesn't exist."""
        with patch.object(gha, "TOKEN_FILE", Path("/tmp/nonexistent_token.json")):
            assert gha.is_authenticated() is False

    def test_is_authenticated_with_token_file(self):
        """Test is_authenticated returns True when token file exists."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"refresh_token": "test_token"}, f)
            temp_path = Path(f.name)

        try:
            with patch.object(gha, "TOKEN_FILE", temp_path):
                assert gha.is_authenticated() is True
        finally:
            temp_path.unlink()

    @patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": ""}, clear=False)
    def test_get_auth_url_missing_credentials(self):
        """Test get_auth_url raises ValueError when credentials are missing."""
        # Temporarily clear credentials
        with patch.object(gha, "CLIENT_ID", ""):
            with patch.object(gha, "CLIENT_SECRET", ""):
                with pytest.raises(ValueError, match="GOOGLE_CLIENT_ID"):
                    gha.get_auth_url()

    @patch.dict(
        os.environ,
        {"GOOGLE_CLIENT_ID": "test_id", "GOOGLE_CLIENT_SECRET": "test_secret"},
        clear=False,
    )
    @patch("services.api_core.google_home_api.Flow")
    def test_get_auth_url_success(self, mock_flow_class):
        """Test get_auth_url returns proper URL with valid credentials."""
        # Mock the Flow behavior
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = ("https://accounts.google.com/auth?test=1", None)
        mock_flow_class.from_client_config.return_value = mock_flow

        with patch.object(gha, "CLIENT_ID", "test_id"):
            with patch.object(gha, "CLIENT_SECRET", "test_secret"):
                url = gha.get_auth_url()

                assert isinstance(url, str)
                assert url.startswith("https://")
                mock_flow.authorization_url.assert_called_once()

    @patch("services.api_core.google_home_api.Flow")
    def test_handle_oauth_callback_success(self, mock_flow_class):
        """Test handle_oauth_callback successfully saves tokens."""
        # Mock Flow and credentials
        mock_creds = MagicMock()
        mock_creds.refresh_token = "test_refresh_token"
        mock_creds.token_uri = "https://oauth2.googleapis.com/token"
        mock_creds.client_id = "test_id"
        mock_creds.client_secret = "test_secret"
        mock_creds.scopes = gha.SCOPES

        mock_flow = MagicMock()
        mock_flow.credentials = mock_creds
        mock_flow_class.from_client_config.return_value = mock_flow

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_token_file = Path(tmpdir) / "test_tokens.json"

            with patch.object(gha, "CLIENT_ID", "test_id"):
                with patch.object(gha, "CLIENT_SECRET", "test_secret"):
                    with patch.object(gha, "TOKEN_FILE", temp_token_file):
                        result = gha.handle_oauth_callback("test_code")

                        assert result["ok"] is True
                        assert "message" in result
                        assert temp_token_file.exists()

                        # Verify token content
                        with open(temp_token_file) as f:
                            tokens = json.load(f)
                        assert tokens["refresh_token"] == "test_refresh_token"

    def test_get_devices_no_project_id(self):
        """Test get_devices returns error when PROJECT_ID is not set."""
        with patch.object(gha, "PROJECT_ID", ""):
            result = gha.get_devices()
            assert result["ok"] is False
            assert "PROJECT_ID" in result["error"]

    @patch("services.api_core.google_home_api.refresh_access_token")
    @patch("services.api_core.google_home_api.requests.get")
    def test_get_devices_success(self, mock_get, mock_refresh):
        """Test get_devices successfully retrieves devices."""
        # Mock token refresh
        mock_refresh.return_value = "test_access_token"

        # Mock API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "devices": [
                {
                    "name": "enterprises/test/devices/123",
                    "type": "sdm.devices.types.LIGHT",
                    "traits": {"sdm.devices.traits.OnOff": {"on": True}},
                }
            ]
        }
        mock_get.return_value = mock_response

        with patch.object(gha, "PROJECT_ID", "test_project"):
            result = gha.get_devices()

            assert result["ok"] is True
            assert "devices" in result
            assert len(result["devices"]) == 1
            assert result["devices"][0]["type"] == "sdm.devices.types.LIGHT"

    @patch("services.api_core.google_home_api.refresh_access_token")
    @patch("services.api_core.google_home_api.requests.post")
    def test_send_command_success(self, mock_post, mock_refresh):
        """Test send_command successfully sends commands to devices."""
        # Mock token refresh
        mock_refresh.return_value = "test_access_token"

        # Mock API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "{}"
        mock_response.json.return_value = {}
        mock_post.return_value = mock_response

        device_id = "enterprises/test/devices/123"
        command = "action.devices.commands.OnOff"
        params = {"on": True}

        result = gha.send_command(device_id, command, params)

        assert result["ok"] is True
        assert "result" in result
        mock_post.assert_called_once()

        # Verify the request payload
        call_args = mock_post.call_args
        assert command in str(call_args)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
