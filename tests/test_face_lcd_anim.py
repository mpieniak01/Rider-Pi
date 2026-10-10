import os
import time

import pytest

from services.api_core import face_anim as animation
from services.api_server import app

PNG_PATH = "/tmp/face_latest.png"


@pytest.fixture
def client():
    animation.stop({})
    yield app.test_client()
    animation.stop({})


@pytest.mark.skipif(os.environ.get("FACE_SINK") == "lcd", reason="Brak LCD w CI")
def test_file_sink_anim(client, monkeypatch):
    monkeypatch.setenv("FACE_SINK", "file")
    # Stop any running animation
    client.post("/face/stop", json={})
    # Start animation
    r = client.post("/face/play", json={"expr": "happy", "fps": 10, "sink": "file"})
    assert r.status_code == 200
    time.sleep(2)
    assert os.path.exists(PNG_PATH)
    assert os.path.getsize(PNG_PATH) > 1024
    # Stop
    r2 = client.post("/face/stop", json={})
    assert r2.status_code == 200
    state = client.get("/face/state").get_json()
    assert not state["state"]["playing"]


@pytest.mark.skipif(True, reason="Brak LCD w CI")
def test_lcd_sink_no_hw(client):
    os.environ["FACE_SINK"] = "lcd"
    client.post("/face/stop", json={})
    r = client.post("/face/play", json={"expr": "happy", "fps": 10, "sink": "lcd"})
    assert r.status_code == 503
    data = r.get_json()
    assert data["ok"] is False
    assert data["status"] == 503
    assert "LCD not available" in data["error"] or "LCD" in data["error"]


def test_render_and_legacy(client):
    # /face/render
    r = client.post("/face/render", json={"expr": "happy"}, headers={"Accept": "image/png"})
    assert r.status_code == 200
    ct = r.headers.get("Content-Type", "")
    if ct.startswith("image/png"):
        assert r.data and len(r.data) > 0
    else:
        data = r.get_json()
        assert isinstance(data, dict)
    # /api/draw/face
    r2 = client.post("/api/draw/face", json={"expr": "happy"}, headers={"Accept": "image/png"})
    assert r2.status_code == 200
    ct2 = r2.headers.get("Content-Type", "")
    if ct2.startswith("image/png"):
        assert r2.data and len(r2.data) > 0
    else:
        data2 = r2.get_json()
        assert isinstance(data2, dict)
