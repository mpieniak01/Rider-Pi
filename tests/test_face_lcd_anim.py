import os
import time

import pytest
import requests

API = "http://127.0.0.1:8080"
PNG_PATH = "/tmp/face_latest.png"


@pytest.mark.skipif(os.environ.get("FACE_SINK") == "lcd", reason="Brak LCD w CI")
def test_file_sink_anim():
    os.environ["FACE_SINK"] = "file"
    # Stop any running animation
    requests.post(f"{API}/face/stop", json={})
    # Start animation
    r = requests.post(f"{API}/face/play", json={"expr": "happy", "fps": 10, "sink": "file"})
    assert r.status_code == 200
    time.sleep(2)
    assert os.path.exists(PNG_PATH)
    assert os.path.getsize(PNG_PATH) > 1024
    # Stop
    r2 = requests.post(f"{API}/face/stop", json={})
    assert r2.status_code == 200
    state = requests.get(f"{API}/face/state").json()
    assert not state["state"]["playing"]


@pytest.mark.skipif(True, reason="Brak LCD w CI")
def test_lcd_sink_no_hw():
    os.environ["FACE_SINK"] = "lcd"
    requests.post(f"{API}/face/stop", json={})
    r = requests.post(f"{API}/face/play", json={"expr": "happy", "fps": 10, "sink": "lcd"})
    assert r.status_code == 503
    data = r.json()
    assert data["ok"] is False
    assert data["status"] == 503
    assert "LCD not available" in data["error"] or "LCD" in data["error"]


def test_render_and_legacy():
    # /face/render
    r = requests.post(f"{API}/face/render", json={"expr": "happy"}, headers={"Accept": "image/png"})
    assert r.status_code == 200
    ct = r.headers.get("Content-Type", "")
    if ct.startswith("image/png"):
        assert r.content and len(r.content) > 0
    else:
        data = r.json()
        assert isinstance(data, dict)
    # /api/draw/face
    r2 = requests.post(f"{API}/draw/face", json={"expr": "happy"}, headers={"Accept": "image/png"})
    assert r2.status_code == 200
    ct2 = r2.headers.get("Content-Type", "")
    if ct2.startswith("image/png"):
        assert r2.content and len(r2.content) > 0
    else:
        data2 = r2.json()
        assert isinstance(data2, dict)
