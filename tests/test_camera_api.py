import os, io
from services import status_api

def test_state_has_camera_block():
    c = status_api.app.test_client()
    r = c.get("/state")
    assert r.status_code == 200
    j = r.get_json()
    assert "camera" in j
    assert "placeholder_url" in j["camera"]
    assert j["camera"]["preview_url"] == "/camera/last"

def test_camera_placeholder_returns_svg():
    c = status_api.app.test_client()
    r = c.get("/camera/placeholder")
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("image/svg+xml")
    body = r.data.decode()
    assert "Brak podglądu" in body or "placeholder" in body

def test_camera_last_not_existing(monkeypatch, tmp_path):
    # tymczasowo ustaw LAST_FRAME na nieistniejący
    monkeypatch.setattr(status_api, "LAST_FRAME", tmp_path/"nope.jpg")
    c = status_api.app.test_client()
    r = c.get("/camera/last")
    assert r.status_code == 404
