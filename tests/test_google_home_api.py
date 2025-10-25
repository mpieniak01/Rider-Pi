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

    def test_start_oauth_flow_missing_credentials(self):
        """Test start_oauth_flow raises ValueError when credentials are missing."""
        # Temporarily clear credentials
        with patch.object(gha, "CLIENT_ID", ""):
            with patch.object(gha, "CLIENT_SECRET", ""):
                with pytest.raises(ValueError, match="GOOGLE_CLIENT_ID"):
                    gha.start_oauth_flow()

    @patch("services.api_core.google_home_api.InstalledAppFlow")
    def test_start_oauth_flow_success(self, mock_flow_class):
        """Test start_oauth_flow successfully completes OAuth flow."""
        # Mock the Flow behavior
        mock_creds = MagicMock()
        mock_creds.refresh_token = "test_refresh_token"
        mock_creds.token_uri = "https://oauth2.googleapis.com/token"
        mock_creds.client_id = "test_id"
        mock_creds.client_secret = "test_secret"
        mock_creds.scopes = gha.SCOPES

        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = mock_creds
        mock_flow_class.from_client_config.return_value = mock_flow

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_token_file = Path(tmpdir) / "test_tokens.json"

            with patch.object(gha, "CLIENT_ID", "test_id"):
                with patch.object(gha, "CLIENT_SECRET", "test_secret"):
                    with patch.object(gha, "TOKEN_FILE", temp_token_file):
                        result = gha.start_oauth_flow()

                        assert result["ok"] is True
                        assert "message" in result
                        assert temp_token_file.exists()

                        # Verify token content
                        with open(temp_token_file) as f:
                            tokens = json.load(f)
                        assert tokens["refresh_token"] == "test_refresh_token"

                        # Verify run_local_server was called with correct params
                        mock_flow.run_local_server.assert_called_once()
                        call_kwargs = mock_flow.run_local_server.call_args[1]
                        assert call_kwargs["port"] == 8080
                        assert call_kwargs["access_type"] == "offline"
                        assert call_kwargs["prompt"] == "consent"

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

    @patch("services.api_core.google_home_api.refresh_access_token")
    @patch("services.api_core.google_home_api.requests.post")
    def test_send_command_color_temperature(self, mock_post, mock_refresh):
        """Test send_command with ColorAbsolute (temperature) command."""
        mock_refresh.return_value = "test_access_token"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "{}"
        mock_response.json.return_value = {}
        mock_post.return_value = mock_response

        device_id = "enterprises/test/devices/123"
        command = "action.devices.commands.ColorAbsolute"
        params = {"color": {"temperatureK": 3000}}

        result = gha.send_command(device_id, command, params)

        assert result["ok"] is True
        mock_post.assert_called_once()

        # Verify payload structure
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["command"] == command
        assert call_kwargs["json"]["params"]["color"]["temperatureK"] == 3000

    @patch("services.api_core.google_home_api.refresh_access_token")
    @patch("services.api_core.google_home_api.requests.post")
    def test_send_command_color_rgb(self, mock_post, mock_refresh):
        """Test send_command with ColorAbsolute (RGB) command."""
        mock_refresh.return_value = "test_access_token"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "{}"
        mock_response.json.return_value = {}
        mock_post.return_value = mock_response

        device_id = "enterprises/test/devices/123"
        command = "action.devices.commands.ColorAbsolute"
        params = {"color": {"spectrumRgb": 16711680}}

        result = gha.send_command(device_id, command, params)

        assert result["ok"] is True
        mock_post.assert_called_once()

        # Verify payload structure
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["params"]["color"]["spectrumRgb"] == 16711680

    @patch("services.api_core.google_home_api.refresh_access_token")
    @patch("services.api_core.google_home_api.requests.post")
    def test_send_command_thermostat_setpoint(self, mock_post, mock_refresh):
        """Test send_command with ThermostatTemperatureSetpoint command."""
        mock_refresh.return_value = "test_access_token"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "{}"
        mock_response.json.return_value = {}
        mock_post.return_value = mock_response

        device_id = "enterprises/test/devices/123"
        command = "action.devices.commands.ThermostatTemperatureSetpoint"
        params = {"thermostatTemperatureSetpoint": 22.5}

        result = gha.send_command(device_id, command, params)

        assert result["ok"] is True
        mock_post.assert_called_once()

        # Verify payload structure
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["params"]["thermostatTemperatureSetpoint"] == 22.5

    @patch("services.api_core.google_home_api.refresh_access_token")
    @patch("services.api_core.google_home_api.requests.post")
    def test_send_command_thermostat_mode(self, mock_post, mock_refresh):
        """Test send_command with ThermostatSetMode command."""
        mock_refresh.return_value = "test_access_token"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "{}"
        mock_response.json.return_value = {}
        mock_post.return_value = mock_response

        device_id = "enterprises/test/devices/123"
        command = "action.devices.commands.ThermostatSetMode"
        params = {"thermostatMode": "heat"}

        result = gha.send_command(device_id, command, params)

        assert result["ok"] is True
        mock_post.assert_called_once()

        # Verify payload structure
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["params"]["thermostatMode"] == "heat"

    @patch("services.api_core.google_home_api.refresh_access_token")
    @patch("services.api_core.google_home_api.requests.post")
    def test_send_command_start_stop(self, mock_post, mock_refresh):
        """Test send_command with StartStop command."""
        mock_refresh.return_value = "test_access_token"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "{}"
        mock_response.json.return_value = {}
        mock_post.return_value = mock_response

        device_id = "enterprises/test/devices/123"
        command = "action.devices.commands.StartStop"
        params = {"start": True}

        result = gha.send_command(device_id, command, params)

        assert result["ok"] is True
        mock_post.assert_called_once()

        # Verify payload structure
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["params"]["start"] is True

    @patch("services.api_core.google_home_api.refresh_access_token")
    @patch("services.api_core.google_home_api.requests.post")
    def test_send_command_dock(self, mock_post, mock_refresh):
        """Test send_command with Dock command."""
        mock_refresh.return_value = "test_access_token"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "{}"
        mock_response.json.return_value = {}
        mock_post.return_value = mock_response

        device_id = "enterprises/test/devices/123"
        command = "action.devices.commands.Dock"
        params = {}

        result = gha.send_command(device_id, command, params)

        assert result["ok"] is True
        mock_post.assert_called_once()

        # Verify payload structure
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["command"] == "action.devices.commands.Dock"
        assert call_kwargs["json"]["params"] == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
