#!/usr/bin/env python3
"""
Basic tests for Google Feed integration.
Tests bridge worker and API endpoints without requiring actual Google credentials.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Import modules we're testing
from services.api_core import google_proxy


class TestGoogleFeedAPI:
    """Test suite for Google Feed API proxy."""

    def test_read_json_file_exists(self):
        """Test _read_json_file with valid file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            test_data = {"state": "ok", "timestamp": 123456}
            json.dump(test_data, f)
            temp_path = Path(f.name)

        try:
            result = google_proxy._read_json_file(temp_path)
            assert result == test_data
        finally:
            temp_path.unlink()

    def test_read_json_file_not_exists(self):
        """Test _read_json_file with non-existent file returns default."""
        nonexistent = Path(tempfile.gettempdir()) / "nonexistent_test_file_12345.json"
        result = google_proxy._read_json_file(nonexistent, {"default": True})
        assert result == {"default": True}

    def test_read_json_file_invalid_json(self):
        """Test _read_json_file with invalid JSON returns default."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("invalid json content")
            temp_path = Path(f.name)

        try:
            result = google_proxy._read_json_file(temp_path, {"error": True})
            assert result == {"error": True}
        finally:
            temp_path.unlink()

    def test_blueprint_created(self):
        """Test that the blueprint is properly created."""
        assert google_proxy.google_proxy is not None
        assert google_proxy.google_proxy.name == "google_proxy"
        assert google_proxy.google_proxy.url_prefix == "/api/google"

    def test_get_status_endpoint(self):
        """Test /api/google/status endpoint returns valid JSON."""
        from flask import Flask

        app = Flask(__name__)
        app.register_blueprint(google_proxy.google_proxy)

        with app.test_client() as client:
            # Test with non-existent status file
            nonexistent = Path(tempfile.gettempdir()) / "nonexistent_status_test.json"
            with patch.object(google_proxy, "STATUS_FILE", nonexistent):
                response = client.get("/api/google/status")
                assert response.status_code == 200
                data = response.get_json()
                assert "state" in data
                assert data["state"] == "off"
                assert "timestamp" in data
                assert "metrics" in data

    def test_get_status_endpoint_with_data(self):
        """Test /api/google/status endpoint with valid data."""
        from flask import Flask

        app = Flask(__name__)
        app.register_blueprint(google_proxy.google_proxy)

        # Create temp status file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            status_data = {
                "state": "ok",
                "timestamp": 123456.789,
                "metrics": {"errors_24h": 0, "requests_24h": 5},
            }
            json.dump(status_data, f)
            temp_path = Path(f.name)

        try:
            with patch.object(google_proxy, "STATUS_FILE", temp_path):
                with app.test_client() as client:
                    response = client.get("/api/google/status")
                    assert response.status_code == 200
                    data = response.get_json()
                    assert data["state"] == "ok"
                    assert data["timestamp"] == 123456.789
                    assert data["metrics"]["requests_24h"] == 5
        finally:
            temp_path.unlink()

    def test_get_last_snapshot_not_exists(self):
        """Test /api/google/raw/last.json returns 404 when no snapshot."""
        from flask import Flask

        app = Flask(__name__)
        app.register_blueprint(google_proxy.google_proxy)

        with app.test_client() as client:
            nonexistent = Path(tempfile.gettempdir()) / "nonexistent_last_test.json"
            with patch.object(google_proxy, "LAST_FILE", nonexistent):
                response = client.get("/api/google/raw/last.json")
                assert response.status_code == 404
                data = response.get_json()
                assert data["error"] == "no_snapshot"

    def test_get_last_snapshot_with_data(self):
        """Test /api/google/raw/last.json returns snapshot data."""
        from flask import Flask

        app = Flask(__name__)
        app.register_blueprint(google_proxy.google_proxy)

        # Create temp snapshot file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            snapshot_data = {
                "data": {"service": "google_feed", "status": "test"},
                "timestamp": 123456.789,
            }
            json.dump(snapshot_data, f)
            temp_path = Path(f.name)

        try:
            with patch.object(google_proxy, "LAST_FILE", temp_path):
                with app.test_client() as client:
                    response = client.get("/api/google/raw/last.json")
                    assert response.status_code == 200
                    data = response.get_json()
                    assert "data" in data
                    assert data["data"]["service"] == "google_feed"
        finally:
            temp_path.unlink()


class TestGoogleBridgePuller:
    """Test suite for Google Bridge puller worker."""

    def test_puller_imports(self):
        """Test that puller module imports successfully."""
        from apps.google_bridge import puller

        assert puller is not None

    def test_puller_has_main(self):
        """Test that puller has a main function."""
        from apps.google_bridge import puller

        assert hasattr(puller, "main")
        assert callable(puller.main)

    def test_puller_pseudocall(self):
        """Test pseudocall_google returns expected structure."""
        from apps.google_bridge import puller

        result = puller.pseudocall_google()
        assert isinstance(result, dict)
        assert "service" in result
        assert result["service"] == "google_feed"
        assert "timestamp" in result

    def test_write_status(self):
        """Test write_status function."""
        from apps.google_bridge import puller

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            status_file = tmppath / "status.json"

            with patch.object(puller, "STATUS_FILE", status_file):
                puller.write_status("ok", 123456.0, errors_24h=1, requests_24h=10)

                assert status_file.exists()
                data = json.loads(status_file.read_text())
                assert data["state"] == "ok"
                assert data["timestamp"] == 123456.0
                assert data["metrics"]["errors_24h"] == 1
                assert data["metrics"]["requests_24h"] == 10

    def test_write_snapshot_with_data(self):
        """Test write_snapshot function with data."""
        from apps.google_bridge import puller

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            last_file = tmppath / "last.json"

            with patch.object(puller, "LAST_FILE", last_file):
                test_data = {"service": "test", "value": 42}
                puller.write_snapshot(data=test_data)

                assert last_file.exists()
                data = json.loads(last_file.read_text())
                assert "data" in data
                assert data["data"]["service"] == "test"
                assert data["data"]["value"] == 42
                assert "timestamp" in data

    def test_write_snapshot_with_error(self):
        """Test write_snapshot function with error."""
        from apps.google_bridge import puller

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            last_file = tmppath / "last.json"

            with patch.object(puller, "LAST_FILE", last_file):
                puller.write_snapshot(error="test error")

                assert last_file.exists()
                data = json.loads(last_file.read_text())
                assert "error" in data
                assert data["error"] == "test error"
                assert "timestamp" in data

    def test_poll_google(self):
        """Test poll_google function."""
        from apps.google_bridge import puller

        success, data, error = puller.poll_google()
        assert success is True
        assert data is not None
        assert isinstance(data, dict)
        assert error is None
