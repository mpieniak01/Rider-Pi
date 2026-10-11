"""Targeted software checks; no LCD, UART or command bus."""

import pytest
from flask import Flask

from services.api_core import face_studio


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FACE_STUDIO_LIBRARY", str(tmp_path / "library.json"))
    app = Flask(__name__)
    face_studio.register(app)
    return app.test_client()


def gesture():
    return {
        "name": "Hello",
        "duration": 1,
        "expr": "happy",
        "initial": {},
        "tracks": {"mouth.open": [{"t0": 0, "t1": 1, "v0": 0, "v1": 1, "ease": "lin"}]},
    }


def test_library_lifecycle(client):
    builtins = client.get("/api/face-studio/gestures").get_json()["gestures"]
    assert {g["id"] for g in builtins} >= {"builtin:blink", "builtin:look"}
    saved = client.post("/api/face-studio/gestures", json=gesture()).get_json()
    key = saved["id"]
    assert saved["actuation"] is False
    updated = client.post("/api/face-studio/gestures", json={**gesture(), "id": key, "name": "New"})
    assert updated.status_code == 200
    assert client.get("/api/face-studio/gestures").get_json()["gestures"][-1]["name"] == "New"
    assert client.delete("/api/face-studio/gestures/" + key).status_code == 200
    assert client.delete("/api/face-studio/gestures/" + key).status_code == 404


def test_builtin_cannot_be_overwritten(client):
    assert client.post("/api/face-studio/gestures", json={**gesture(), "id": "builtin:blink"}).status_code == 400


@pytest.mark.parametrize(
    "patch",
    [
        {"duration": -1},
        {"duration": "1"},
        {"expr": []},
        {"name": ""},
        {"tracks": {"motor.speed": []}},
        {"initial": {"eyes.dx": 2}},
        {"tracks": {"eyes.dx": [{"t0": 1, "t1": 0, "v0": 0, "v1": 0}]}},
    ],
)
def test_reject_invalid_gestures(client, patch):
    assert client.post("/api/face-studio/gestures", json={**gesture(), **patch}).status_code == 400


def test_preview_is_repeatable_and_changes_with_time(client):
    def frame(at):
        return client.post("/api/face-studio/frame", json={**gesture(), "at": at})

    first = frame(0)
    assert first.status_code == 200
    assert first.mimetype == "image/png"
    assert first.data.startswith(b"\x89PNG")
    assert first.data == frame(0).data
    assert first.data != frame(1).data
    assert frame(2).status_code == 400


def test_brow_parameters_are_rendered(client):
    base = {**gesture(), "at": 0}
    normal = client.post("/api/face-studio/frame", json=base).data
    changed = client.post("/api/face-studio/frame", json={**base, "initial": {"brows.lift": 1, "brows.tilt": 1}}).data
    assert normal != changed
