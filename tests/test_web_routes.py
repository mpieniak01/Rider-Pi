"""
Tests for web routes to verify proper handling of static files and simple paths.

Updated contract (post #170 clean-up):
- GET /web/assets/i18n.js?v=1 → 200 (no 3xx redirects)
- GET /home → 200   (krótka trasa zamiast /web/home/)
- GET /chat → 200   (jeśli serwowane jako /web/chat.html – testuje plik)
- GET /camera/last?t=0 → not a redirect (3xx niedozwolone)
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
    """Test that /web/assets/i18n.js returns 200 without redirect (no 3xx)."""
    _requires_api()
    c = api.app.test_client()

    # Test without query params
    r = c.get("/web/assets/i18n.js")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    assert (
        "text/javascript" in r.headers.get("Content-Type", "").lower()
        or "application/javascript" in r.headers.get("Content-Type", "").lower()
    )

    # Test with query params (cache busting)
    r = c.get("/web/assets/i18n.js?v=1")
    assert r.status_code == 200, f"Expected 200 for /web/assets/i18n.js?v=1, got {r.status_code}"

    r = c.get("/web/assets/i18n.js?v=3")
    assert r.status_code == 200, f"Expected 200 for /web/assets/i18n.js?v=3, got {r.status_code}"


def test_home_route_ok():
    """`/home` to krótka, wspierana trasa (plik web/home.html)."""
    _requires_api()
    c = api.app.test_client()

    r = c.get("/home", follow_redirects=False)
    assert 200 <= r.status_code < 300, f"/home should be 2xx, got {r.status_code}"
    assert "text/html" in r.headers.get("Content-Type", "").lower()


def test_web_directory_deprecated():
    """`/web/home/` jest świadomie niewspierane — oczekujemy 404 (brak tras katalogowych)."""
    _requires_api()
    c = api.app.test_client()

    r = c.get("/web/home/", follow_redirects=False)
    assert r.status_code == 404, f"/web/home/ should be 404, got {r.status_code}"


def test_chat_route():
    """Test that /web/chat.html exists (static chat page)."""
    _requires_api()
    c = api.app.test_client()

    r = c.get("/web/chat.html")
    assert r.status_code == 200, f"Expected 200 for /web/chat.html, got {r.status_code}"
    assert "text/html" in r.headers.get("Content-Type", "").lower()


def test_navigation_page_no_redirect():
    """Test that /navigation returns 200 without redirect (no 3xx)."""
    _requires_api()
    c = api.app.test_client()

    r = c.get("/navigation")
    assert r.status_code == 200, f"Expected 200 for /navigation, got {r.status_code}"
    assert "text/html" in r.headers.get("Content-Type", "").lower()
    # Verify it's the navigation HTML page
    assert b"Wizualizator Nawigacji" in r.data or b"navigation" in r.data.lower()


def test_camera_last_with_query_params():
    """Test that /camera/last?t=0 does not redirect (3xx)."""
    _requires_api()
    c = api.app.test_client()

    r = c.get("/camera/last?t=0")
    # Kamera może zwrócić 200/404/503 zależnie od dostępności,
    # ale nie może być przekierowania.
    assert r.status_code not in (301, 302, 308), f"Unexpected redirect: {r.status_code}"


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

    r = c.get("/web/assets/i18n.js")
    if r.status_code == 200:
        cache_control = r.headers.get("Cache-Control", "").lower()
        assert "no-store" in cache_control or "no-cache" in cache_control, "Should have anti-cache headers"


def test_web_static_files_no_trailing_slash_redirect():
    """Static files should not redirect when called without trailing slash."""
    _requires_api()
    c = api.app.test_client()

    # Test various static file paths
    test_files = [
        "/web/assets/i18n.js",
        "/web/view.html",
        "/web/control.html",
    ]

    for file_path in test_files:
        r = c.get(file_path, follow_redirects=False)
        # Should either be 200 or 404, but NOT a redirect
        assert r.status_code not in (
            301,
            302,
            308,
        ), f"{file_path} should not redirect; got {r.status_code}"
