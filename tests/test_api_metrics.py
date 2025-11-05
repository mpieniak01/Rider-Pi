#!/usr/bin/env python3
"""
Tests for API metrics endpoint and collection logic.
Validates that /api/app-metrics returns correct structure and that
metrics are counted properly for interactive endpoints.
"""

import pytest

# Check if we can import the required modules
try:
    import services.api_server  # noqa: F401

    API_SERVER_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    API_SERVER_AVAILABLE = False


@pytest.mark.skipif(not API_SERVER_AVAILABLE, reason="API server dependencies not available")
class TestApiMetricsEndpoint:
    """Test suite for /api/app-metrics endpoint."""

    def test_app_metrics_endpoint_exists(self):
        """Test that app_metrics endpoint is registered."""
        import services.api_server as api_server

        # Check that the route exists
        rules = {r.rule for r in api_server.app.url_map.iter_rules()}
        assert "/api/app-metrics" in rules

    def test_app_metrics_returns_json_structure(self):
        """Test that /api/app-metrics returns expected JSON structure."""
        import services.api_server as api_server

        with api_server.app.test_client() as client:
            response = client.get("/api/app-metrics")
            assert response.status_code == 200
            data = response.get_json()

            # Verify basic structure
            assert data is not None
            assert "ok" in data
            assert data["ok"] is True
            assert "metrics" in data
            assert "total_errors" in data

            # Verify all expected groups are present
            expected_groups = ["control", "navigator", "voice", "google_home", "chat", "face"]
            for group in expected_groups:
                assert group in data["metrics"]
                assert "ok" in data["metrics"][group]
                assert "error" in data["metrics"][group]

    def test_app_metrics_counter_types(self):
        """Test that metrics counters are integers."""
        import services.api_server as api_server

        with api_server.app.test_client() as client:
            response = client.get("/api/app-metrics")
            data = response.get_json()

            # Check that total_errors is an integer
            assert isinstance(data["total_errors"], int)

            # Check that all group counters are integers
            for _group, counts in data["metrics"].items():
                assert isinstance(counts["ok"], int)
                assert isinstance(counts["error"], int)


@pytest.mark.skipif(not API_SERVER_AVAILABLE, reason="API server dependencies not available")
class TestApiMetricsCounting:
    """Test suite for API metrics counting logic."""

    def setup_method(self):
        """Reset metrics before each test."""
        import services.api_core.compat as compat

        # Reset all counters (thread-safe)
        with compat.API_METRICS_LOCK:
            for group in compat.API_METRICS:
                compat.API_METRICS[group]["ok"] = 0
                compat.API_METRICS[group]["error"] = 0
            compat.API_METRICS_TOTAL["errors"] = 0

    def test_control_endpoint_increments_control_metrics(self):
        """Test that /api/control calls increment control metrics."""
        import services.api_server as api_server

        with api_server.app.test_client() as client:
            # Make a call to control endpoint
            client.post("/api/control", json={"dir": "forward", "v": 0.1, "t": 0.1})

            # Get metrics
            metrics_response = client.get("/api/app-metrics")
            data = metrics_response.get_json()

            # Control metrics should be incremented
            # Note: may be ok or error depending on backend availability, but should be counted
            total_control = data["metrics"]["control"]["ok"] + data["metrics"]["control"]["error"]
            assert total_control >= 1

    def test_navigator_start_increments_navigator_metrics(self):
        """Test that /api/navigator/start calls increment navigator metrics."""
        import services.api_server as api_server

        with api_server.app.test_client() as client:
            # Make a call to navigator start endpoint
            client.post("/api/navigator/start", json={})

            # Get metrics
            metrics_response = client.get("/api/app-metrics")
            data = metrics_response.get_json()

            # Navigator metrics should be incremented
            total_navigator = data["metrics"]["navigator"]["ok"] + data["metrics"]["navigator"]["error"]
            assert total_navigator >= 1

    def test_voice_endpoint_increments_voice_metrics(self):
        """Test that /api/voice/capture calls increment voice metrics."""
        import services.api_server as api_server

        with api_server.app.test_client() as client:
            # Make a call to voice endpoint
            client.post("/api/voice/capture", json={})

            # Get metrics
            metrics_response = client.get("/api/app-metrics")
            data = metrics_response.get_json()

            # Voice metrics should be incremented
            total_voice = data["metrics"]["voice"]["ok"] + data["metrics"]["voice"]["error"]
            assert total_voice >= 1

    def test_system_endpoints_not_counted(self):
        """Test that system endpoints like /healthz are not counted in metrics."""
        import services.api_server as api_server

        with api_server.app.test_client() as client:
            # Get baseline metrics
            baseline_response = client.get("/api/app-metrics")
            baseline_data = baseline_response.get_json()

            # Call system endpoints
            client.get("/healthz")
            client.get("/state")
            client.get("/sysinfo")
            client.get("/metrics")

            # Get metrics again
            after_response = client.get("/api/app-metrics")
            after_data = after_response.get_json()

            # Metrics should be unchanged (all groups should have same counts)
            for group in baseline_data["metrics"]:
                assert baseline_data["metrics"][group] == after_data["metrics"][group]

    def test_app_metrics_endpoint_not_counted(self):
        """Test that /api/app-metrics calls don't count themselves."""
        import services.api_server as api_server

        with api_server.app.test_client() as client:
            # Get baseline metrics
            baseline_response = client.get("/api/app-metrics")
            baseline_data = baseline_response.get_json()

            # Call app-metrics multiple times
            client.get("/api/app-metrics")
            client.get("/api/app-metrics")
            client.get("/api/app-metrics")

            # Get metrics again
            after_response = client.get("/api/app-metrics")
            after_data = after_response.get_json()

            # Metrics should be unchanged
            for group in baseline_data["metrics"]:
                assert baseline_data["metrics"][group] == after_data["metrics"][group]

    def test_error_responses_increment_error_counter(self):
        """Test that 4xx/5xx responses increment error counters."""
        import services.api_server as api_server

        with api_server.app.test_client() as client:
            # Get baseline
            baseline_response = client.get("/api/app-metrics")
            baseline_data = baseline_response.get_json()
            baseline_total_errors = baseline_data["total_errors"]

            # Make a request that should fail (missing required fields)
            client.post("/api/home/command", json={})

            # Get metrics again
            after_response = client.get("/api/app-metrics")
            after_data = after_response.get_json()

            # Total errors should have increased
            assert after_data["total_errors"] > baseline_total_errors

    def test_vision_endpoints_not_counted(self):
        """Test that vision/camera endpoints are not counted."""
        import services.api_server as api_server

        with api_server.app.test_client() as client:
            # Get baseline metrics
            baseline_response = client.get("/api/app-metrics")
            baseline_data = baseline_response.get_json()

            # Call vision endpoints (these should not be counted)
            client.get("/camera/last")
            client.get("/snapshots/raw.jpg")

            # Get metrics again
            after_response = client.get("/api/app-metrics")
            after_data = after_response.get_json()

            # Metrics should be unchanged
            for group in baseline_data["metrics"]:
                assert baseline_data["metrics"][group] == after_data["metrics"][group]


@pytest.mark.skipif(not API_SERVER_AVAILABLE, reason="API server dependencies not available")
class TestApiMetricsCompatModule:
    """Test suite for metrics definitions in compat module."""

    def test_api_metrics_defined_in_compat(self):
        """Test that API_METRICS is defined in compat module."""
        import services.api_core.compat as compat

        assert hasattr(compat, "API_METRICS")
        assert isinstance(compat.API_METRICS, dict)

        # Verify expected groups
        expected_groups = ["control", "navigator", "voice", "google_home", "chat", "face"]
        for group in expected_groups:
            assert group in compat.API_METRICS
            assert "ok" in compat.API_METRICS[group]
            assert "error" in compat.API_METRICS[group]

    def test_total_errors_defined_in_compat(self):
        """Test that API_METRICS_TOTAL is defined in compat module."""
        import services.api_core.compat as compat

        assert hasattr(compat, "API_METRICS_TOTAL")
        assert isinstance(compat.API_METRICS_TOTAL, dict)
        assert "errors" in compat.API_METRICS_TOTAL
        assert isinstance(compat.API_METRICS_TOTAL["errors"], int)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
