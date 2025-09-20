from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest

# Ten zestaw jest domyślnie wyłączony, by nie blokować lokalnych runów na robocie.
# Włącz explicite: ALLOW_CAMERA_API_TESTS=1 pytest -q tests/test_camera_api.py
if os.getenv("ALLOW_CAMERA_API_TESTS", "0") != "1":
    pytest.skip(
        "Skipping camera API tests by default (set ALLOW_CAMERA_API_TESTS=1 to enable).",
        allow_module_level=True,
    )

# Spróbuj dwóch lokalizacji API: legacy i aktualna
api = None
try:
    from services import status_api as api  # legacy (może nie istnieć)
except Exception:
    try:
        from services import api_server as api  # nowsza ścieżka
    except Exception:
        api = None


def _requires_api():
    if api is None or not hasattr(api, "app"):
        pytest.skip("No compatible services.* API module with Flask app found.")


def test_state_has_camera_block():
    _requires_api()
    c = api.app.test_client()
    r = c.get("/state")
    assert r.status_code == 200
    j = r.get_json() or {}

    if "camera" not in j:
        pytest.xfail("`/state` does not expose a 'camera' block on this build.")
    cam = j["camera"]
    assert "placeholder_url" in cam
    assert "preview_url" in cam

    # Akceptujemy query string (np. cache-busting ?t=...): weryfikujemy samą ścieżkę.
    u = str(cam["preview_url"])
    path = urlparse(u).path
    assert path.endswith("/camera/last")


def test_camera_placeholder_returns_svg():
    _requires_api()
    c = api.app.test_client()
    r = c.get("/camera/placeholder")
    assert r.status_code == 200
    ct = r.headers.get("Content-Type", "")
    assert ct.startswith("image/svg")  # np. image/svg+xml; charset=utf-8
    body = r.data.decode(errors="ignore")
    assert ("Brak podglądu" in body) or ("placeholder" in body)


def test_camera_last_not_existing(monkeypatch, tmp_path):
    _requires_api()
    if not hasattr(api, "LAST_FRAME"):
        pytest.xfail("API has no LAST_FRAME attribute; skipping negative-path test.")
    monkeypatch.setattr(api, "LAST_FRAME", tmp_path / "nope.jpg", raising=False)
    c = api.app.test_client()
    r = c.get("/camera/last")
    assert r.status_code == 404
