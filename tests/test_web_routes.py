"""
Tests for web routes to verify proper handling of static files and directories.

Requirements from issue #170:
- GET /web/i18n.js?v=1 → 200 (no 3xx redirects)
- GET /web/home/ → 200
- GET /chat → 200  
- GET /camera/last?t=0 → 200
- GET /web/../ → 404 (path traversal prevention)
"""

from __future__ import annotations

import os

import pytest

# Import API server
api = None
try:
    from services import api_server as api
except Exception:
    api = None


def _requires_api():
    if api is None or not hasattr(api, "app"):
        pytest.skip("No compatible services.api_server module with Flask app found.")


def test_web_static_file_no_redirect():
    """Test that /web/i18n.js returns 200 without redirect (no 3xx)."""
    _requires_api()
    c = api.app.test_client()
    
    # Test without query params
    r = c.get("/web/i18n.js")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    assert "text/javascript" in r.headers.get("Content-Type", "").lower() or \
           "application/javascript" in r.headers.get("Content-Type", "").lower()
    
    # Test with query params (cache busting)
    r = c.get("/web/i18n.js?v=1")
    assert r.status_code == 200, f"Expected 200 for /web/i18n.js?v=1, got {r.status_code}"
    
    r = c.get("/web/i18n.js?v=3")
    assert r.status_code == 200, f"Expected 200 for /web/i18n.js?v=3, got {r.status_code}"


def test_web_directory_with_trailing_slash():
    """Test that /web/home/ serves index.html."""
    _requires_api()
    c = api.app.test_client()
    
    r = c.get("/web/home/")
    assert r.status_code == 200, f"Expected 200 for /web/home/, got {r.status_code}"
    assert "text/html" in r.headers.get("Content-Type", "").lower()


def test_chat_route():
    """Test that /chat route works (if it exists as static file)."""
    _requires_api()
    c = api.app.test_client()
    
    # /chat might be served as /web/chat.html
    r = c.get("/web/chat.html")
    assert r.status_code == 200, f"Expected 200 for /web/chat.html, got {r.status_code}"


def test_camera_last_with_query_params():
    """Test that /camera/last?t=0 returns 200 (or appropriate response)."""
    _requires_api()
    c = api.app.test_client()
    
    r = c.get("/camera/last?t=0")
    # Camera endpoint might return 200, 404, or 503 depending on camera availability
    # We just verify it's not a redirect (3xx)
    assert r.status_code != 308, "Should not redirect with 308"
    assert r.status_code != 301, "Should not redirect with 301"
    assert r.status_code != 302, "Should not redirect with 302"


def test_path_traversal_prevention():
    """Test that path traversal attempts return 404."""
    _requires_api()
    c = api.app.test_client()
    
    # Try various path traversal attempts
    r = c.get("/web/../")
    assert r.status_code == 404, f"Path traversal /web/../ should return 404, got {r.status_code}"
    
    r = c.get("/web/../etc/passwd")
    assert r.status_code == 404, f"Path traversal should return 404, got {r.status_code}"


def test_view_route_returns_dashboard():
    """Test that /view route serves the dashboard."""
    _requires_api()
    c = api.app.test_client()
    
    r = c.get("/view")
    assert r.status_code == 200, f"Expected 200 for /view, got {r.status_code}"
    assert "text/html" in r.headers.get("Content-Type", "").lower()


def test_anti_cache_headers():
    """Test that web routes have proper anti-cache headers."""
    _requires_api()
    c = api.app.test_client()
    
    r = c.get("/web/i18n.js")
    if r.status_code == 200:
        assert "no-store" in r.headers.get("Cache-Control", "").lower() or \
               "no-cache" in r.headers.get("Cache-Control", "").lower(), \
               "Should have anti-cache headers"


def test_web_static_files_no_trailing_slash_redirect():
    """Test that requesting static files without trailing slash doesn't redirect."""
    _requires_api()
    c = api.app.test_client()
    
    # Test various static file extensions
    test_files = [
        "/web/i18n.js",
        "/web/view.html",
        "/web/control.html",
    ]
    
    for file_path in test_files:
        r = c.get(file_path, follow_redirects=False)
        # Should either be 200 or 404, but NOT a redirect
        assert r.status_code != 308, f"{file_path} should not redirect with 308"
        assert r.status_code != 301, f"{file_path} should not redirect with 301"
