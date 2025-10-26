#!/usr/bin/env python3
"""
Tests for Google Home command functionality.
Tests command sending, caching, error handling, and API endpoints.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import modules under test
import services.api_core.google_home_api as gha
from services.api_server import app


class TestGoogleCommandAPI:
    """Test suite for Google Home command API endpoints."""

    @pytest.fixture
    def client(self):
        """Create Flask test client."""
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client

    @pytest.fixture
    def temp_cache_dir(self):
        """Create temporary directory for command cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_command_endpoint_missing_auth(self, client):
        """Test /api/home/command returns 401 when not authenticated."""
        with patch.object(gha, "is_authenticated", return_value=False):
            response = client.post(
                "/api/home/command", json={"deviceId": "test-device", "command": "test-command", "params": {}}
            )
            assert response.status_code == 401
            data = response.get_json()
            assert data["ok"] is False
            assert "authenticated" in data["error"].lower()

    def test_command_endpoint_missing_device_id(self, client):
        """Test /api/home/command returns 400 when deviceId is missing."""
        with patch.object(gha, "is_authenticated", return_value=True):
            response = client.post("/api/home/command", json={"command": "test-command", "params": {}})
            assert response.status_code == 400
            data = response.get_json()
            assert data["ok"] is False
            assert "missing" in data["error"].lower()

    def test_command_endpoint_missing_command(self, client):
        """Test /api/home/command returns 400 when command is missing."""
        with patch.object(gha, "is_authenticated", return_value=True):
            response = client.post("/api/home/command", json={"deviceId": "test-device", "params": {}})
            assert response.status_code == 400
            data = response.get_json()
            assert data["ok"] is False
            assert "missing" in data["error"].lower()

    def test_command_endpoint_success(self, client, temp_cache_dir):
        """Test /api/home/command successfully sends command."""
        with patch.object(gha, "is_authenticated", return_value=True):
            with patch.object(gha, "send_command") as mock_send:
                mock_send.return_value = {"ok": True, "result": {"status": "SUCCESS"}}

                # Patch cache directory
                import services.api_server as api_server

                with patch.object(api_server, "LAST_COMMAND_FILE", temp_cache_dir / "last_command.json"):
                    response = client.post(
                        "/api/home/command",
                        json={
                            "deviceId": "enterprises/project/devices/123",
                            "command": "action.devices.commands.OnOff",
                            "params": {"on": True},
                        },
                    )

                    assert response.status_code == 200
                    data = response.get_json()
                    assert data["ok"] is True
                    assert "result" in data

                    # Verify send_command was called with correct params
                    mock_send.assert_called_once_with(
                        "enterprises/project/devices/123", "action.devices.commands.OnOff", {"on": True}
                    )

                    # Verify cache was created
                    cache_file = temp_cache_dir / "last_command.json"
                    assert cache_file.exists()
                    cache_data = json.loads(cache_file.read_text())
                    assert cache_data["ok"] is True
                    assert cache_data["device_id"] == "enterprises/project/devices/123"
                    assert cache_data["command"] == "action.devices.commands.OnOff"
                    assert cache_data["params"] == {"on": True}
                    assert cache_data["response"] == {"status": "SUCCESS"}

    def test_command_endpoint_error_unauthorized(self, client, temp_cache_dir):
        """Test /api/home/command handles unauthorized error."""
        with patch.object(gha, "is_authenticated", return_value=True):
            with patch.object(gha, "send_command") as mock_send:
                with patch.object(gha, "refresh_access_token", return_value=None):
                    mock_send.return_value = {"ok": False, "error": "Unauthorized", "status_code": 401}

                    import services.api_server as api_server

                    with patch.object(api_server, "LAST_COMMAND_FILE", temp_cache_dir / "last_command.json"):
                        response = client.post(
                            "/api/home/command",
                            json={
                                "deviceId": "enterprises/project/devices/123",
                                "command": "action.devices.commands.OnOff",
                                "params": {"on": True},
                            },
                        )

                        assert response.status_code == 401
                        data = response.get_json()
                        assert data["ok"] is False

                        # Verify cache was created with error
                        cache_file = temp_cache_dir / "last_command.json"
                        assert cache_file.exists()
                        cache_data = json.loads(cache_file.read_text())
                        assert cache_data["ok"] is False
                        assert cache_data["error"] == "Unauthorized"

    def test_command_endpoint_error_network(self, client, temp_cache_dir):
        """Test /api/home/command handles network error."""
        with patch.object(gha, "is_authenticated", return_value=True):
            with patch.object(gha, "send_command") as mock_send:
                mock_send.return_value = {"ok": False, "error": "Network timeout"}

                import services.api_server as api_server

                with patch.object(api_server, "LAST_COMMAND_FILE", temp_cache_dir / "last_command.json"):
                    response = client.post(
                        "/api/home/command",
                        json={
                            "deviceId": "enterprises/project/devices/123",
                            "command": "action.devices.commands.OnOff",
                            "params": {"on": True},
                        },
                    )

                    assert response.status_code == 500
                    data = response.get_json()
                    assert data["ok"] is False

                    # Verify cache was created with error
                    cache_file = temp_cache_dir / "last_command.json"
                    assert cache_file.exists()
                    cache_data = json.loads(cache_file.read_text())
                    assert cache_data["ok"] is False
                    assert "error" in cache_data

    def test_command_cache_created(self, client, temp_cache_dir):
        """Test that command cache file is created with correct structure."""
        with patch.object(gha, "is_authenticated", return_value=True):
            with patch.object(gha, "send_command") as mock_send:
                mock_send.return_value = {"ok": True, "result": {"status": "SUCCESS"}}

                import services.api_server as api_server

                with patch.object(api_server, "LAST_COMMAND_FILE", temp_cache_dir / "last_command.json"):
                    client.post(
                        "/api/home/command",
                        json={
                            "deviceId": "enterprises/project/devices/123",
                            "command": "action.devices.commands.BrightnessAbsolute",
                            "params": {"brightness": 75},
                        },
                    )

                    # Verify cache file structure
                    cache_file = temp_cache_dir / "last_command.json"
                    assert cache_file.exists()
                    cache_data = json.loads(cache_file.read_text())

                    # Check all required fields
                    assert "timestamp" in cache_data
                    assert "device_id" in cache_data
                    assert "command" in cache_data
                    assert "params" in cache_data
                    assert "ok" in cache_data
                    assert cache_data["ok"] is True
                    assert cache_data["response"] == {"status": "SUCCESS"}
                    assert cache_data["error"] is None


class TestGoogleCommandIntegration:
    """Integration tests for Google Home command functionality."""

    def test_send_command_success(self):
        """Test send_command with successful response."""
        with patch("services.api_core.google_home_api.refresh_access_token") as mock_refresh:
            with patch("services.api_core.google_home_api.requests.post") as mock_post:
                mock_refresh.return_value = "test_token"
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.text = '{"status": "SUCCESS"}'
                mock_response.json.return_value = {"status": "SUCCESS"}
                mock_post.return_value = mock_response

                result = gha.send_command(
                    "enterprises/project/devices/123", "action.devices.commands.OnOff", {"on": True}
                )

                assert result["ok"] is True
                assert result["result"]["status"] == "SUCCESS"
                mock_post.assert_called_once()

    def test_send_command_unauthorized(self):
        """Test send_command with unauthorized response."""
        with patch("services.api_core.google_home_api.refresh_access_token") as mock_refresh:
            with patch("services.api_core.google_home_api.requests.post") as mock_post:
                mock_refresh.return_value = "test_token"
                mock_response = MagicMock()
                mock_response.status_code = 401
                mock_post.return_value = mock_response

                result = gha.send_command(
                    "enterprises/project/devices/123", "action.devices.commands.OnOff", {"on": True}
                )

                assert result["ok"] is False
                assert result["error"] == "Unauthorized"
                assert result["status_code"] == 401

    def test_send_command_no_token(self):
        """Test send_command when token refresh fails."""
        with patch("services.api_core.google_home_api.refresh_access_token") as mock_refresh:
            mock_refresh.return_value = None

            result = gha.send_command("enterprises/project/devices/123", "action.devices.commands.OnOff", {"on": True})

            assert result["ok"] is False
            assert "authenticated" in result["error"].lower()
            assert result["status_code"] == 401
