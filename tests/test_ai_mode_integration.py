"""Simple integration test for AI mode API endpoints."""

from __future__ import annotations

import json


import pytest


def test_api_server_imports():
    """Test that API modules import without errors."""
    from common import ai_mode
    from services.api_core import ai_mode_api

    assert ai_mode is not None
    assert ai_mode_api is not None


@pytest.mark.skip(reason="Requires PIL dependency not available in test environment")
def test_ai_mode_endpoint_registration():
    """Test that AI mode endpoints are properly registered."""
    # Import the necessary modules to trigger route registration
    from services import api_server

    # Check if the AI mode handler function exists
    assert hasattr(api_server.ai_mode_api, "ai_mode_handler")
    assert callable(api_server.ai_mode_api.ai_mode_handler)


def test_ai_mode_get_with_client():
    """Test GET endpoint with Flask test client."""
    from flask import Flask

    from services.api_core.ai_mode_api import ai_mode_handler

    app = Flask(__name__)
    app.add_url_rule(
        "/api/system/ai-mode",
        view_func=ai_mode_handler,
        methods=["GET", "PUT", "POST", "OPTIONS"],
    )

    with app.test_client() as client:
        response = client.get("/api/system/ai-mode")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert "mode" in data
        assert data["mode"] in ("local", "pc_offload")
        assert "changed_ts" in data


def test_ai_mode_put_with_client():
    """Test PUT endpoint with Flask test client."""
    from flask import Flask

    from services.api_core.ai_mode_api import ai_mode_handler

    app = Flask(__name__)
    app.add_url_rule(
        "/api/system/ai-mode",
        view_func=ai_mode_handler,
        methods=["GET", "PUT", "POST", "OPTIONS"],
    )

    with app.test_client() as client:
        # Test setting to pc_offload
        response = client.put(
            "/api/system/ai-mode",
            data=json.dumps({"mode": "pc_offload"}),
            content_type="application/json",
        )
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data["mode"] == "pc_offload"

        # Verify it was changed
        response = client.get("/api/system/ai-mode")
        data = json.loads(response.data)
        assert data["mode"] == "pc_offload"

        # Test setting back to local
        response = client.put(
            "/api/system/ai-mode",
            data=json.dumps({"mode": "local"}),
            content_type="application/json",
        )
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data["mode"] == "local"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
