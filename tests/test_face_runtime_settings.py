"""Catalog and worker checks use temporary files and injected sinks only."""

import time

import pytest
from flask import Flask

from apps.ui.face import catalog
from apps.ui.face.controller import FaceController
from services.api_core import face_anim, face_studio


@pytest.fixture
def client(tmp_path, monkeypatch):
    face_anim.stop()
    monkeypatch.setenv("FACE_STUDIO_LIBRARY", str(tmp_path / "gestures.json"))
    monkeypatch.setenv("FACE_RUNTIME_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setattr(face_anim, "OUT_LATEST", str(tmp_path / "latest.png"))
    monkeypatch.setattr(face_anim, "_make_sink", lambda: face_anim.NullSink())
    app = Flask(__name__)
    face_studio.register(app)
    yield app.test_client()
    face_anim.stop()


def wait_for(predicate, seconds=1):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    pytest.fail("worker condition timed out")


def test_descriptor_and_settings_save_never_start_worker(client):
    data = client.get("/api/face-studio/gestures").get_json()
    assert data["descriptors"]["fps"] == {"battery": 6, "cable": 12, "preview": 12}
    result = client.post("/api/face-studio/runtime", json={"style": "minimal", "power_mode": "cable"})
    assert result.status_code == 200
    assert result.get_json()["settings"]["style"] == "minimal"
    assert not result.get_json()["state"]["playing"]


def test_shared_custom_gesture_activation_and_delete(client):
    spec = {"name": "Custom", "duration": 0.5, "initial": {"brows.lift": 0.9}}
    key = client.post("/api/face-studio/gestures", json=spec).get_json()["id"]
    controller = FaceController(style="friendly", idle=False)
    controller.configure(catalog.get_settings())
    assert controller.do(key) is False
    settings = catalog.get_settings()
    client.post("/api/face-studio/runtime", json={"active_gestures": settings["active_gestures"] + [key]})
    controller.configure(catalog.get_settings())
    assert controller.do(key) is True
    assert controller.catalog.get(key)["initial"]["brows.lift"] == 0.9
    client.delete("/api/face-studio/gestures/" + key)
    assert key not in catalog.get_settings()["active_gestures"]


@pytest.mark.parametrize(
    "body",
    [
        {"style": "unknown"},
        {"idle": "yes"},
        {"intensity": 1.2},
        {"tempo": float("inf")},
        {"active_gestures": ["absent"]},
        {"unexpected": 1},
    ],
)
def test_invalid_settings(client, body):
    assert client.post("/api/face-studio/runtime", json=body).status_code == 400


def test_live_preview_does_not_start_worker(client):
    assert client.get("/api/face-studio/runtime/frame").status_code == 404
    assert face_anim.get_state()["state"]["playing"] is False


def test_worker_caps_fps_and_stops_without_extra_frames(client):
    result = client.post("/api/face-studio/runtime/play", json={"sink": "null", "fps": 60})
    assert result.status_code == 200
    wait_for(lambda: face_anim.get_state()["state"]["frame_count"] > 0)
    assert face_anim.get_state()["state"]["fps"] == 6
    frame = client.get("/api/face-studio/runtime/frame")
    assert frame.mimetype == "image/png"
    client.post("/api/face-studio/runtime/stop")
    assert not face_anim._anim._thr.is_alive()
    assert client.get("/api/face-studio/runtime/frame").status_code == 404


def test_battery_idle_expiry_and_single_worker(client):
    face_anim.play({"sink": "null"})
    wait_for(lambda: face_anim.STATE["running"])
    first = face_anim._anim._thr
    face_anim.play({"sink": "null"})
    assert not first.is_alive()
    face_anim._anim.activity = time.monotonic() - 46
    wait_for(lambda: not face_anim.STATE["running"])
    assert not face_anim.STATE["playing"]


def test_runtime_audio_hook_requires_running_face(client):
    assert client.post("/api/face-studio/runtime/event", json={"intent": "audio", "level": 0.5}).status_code == 409
    client.post("/api/face-studio/runtime/play", json={"sink": "null"})
    wait_for(lambda: face_anim.STATE["running"])
    assert client.post("/api/face-studio/runtime/event", json={"intent": "audio", "level": 0.5}).status_code == 200
    assert client.post("/api/face-studio/runtime/event", json={"intent": "audio", "level": 2}).status_code == 409
    assert face_anim._anim.controller.anim.owners["mouth.open"] == "audio"


def test_preview_cache_is_bounded_and_styles_differ(client):
    body = {"name": "Hello", "duration": 1, "expr": "happy", "at": 0}
    first = client.post("/api/face-studio/frame", json={**body, "style": "friendly"}).data
    second = client.post("/api/face-studio/frame", json={**body, "style": "minimal"}).data
    assert first != second
    for index in range(30):
        client.post("/api/face-studio/frame", json={**body, "at": index / 30})
    assert len(face_studio._CACHE) <= face_studio.MAX_CACHED_FRAMES


def test_settings_revision_rejects_stale_browser_and_keeps_saved_values(client):
    first = client.get("/api/face-studio/runtime").get_json()
    stale = first["settings_revision"]
    assert client.post("/api/face-studio/runtime", json={"style": "minimal", "if_revision": stale}).status_code == 200
    result = client.post("/api/face-studio/runtime", json={"style": "legacy", "if_revision": stale})
    assert result.status_code == 409
    assert result.get_json()["error"] == "face_settings_conflict"
    assert catalog.get_settings()["style"] == "minimal"


def test_preview_defaults_match_runtime_final_expression_pose(client):
    from io import BytesIO

    from PIL import Image, ImageChops

    body = {"name": "My mood", "expr": "surprised", "duration": 1}
    image = Image.open(BytesIO(client.post("/api/face-studio/frame", json={**body, "at": 1}).data)).convert("RGB")
    key = client.post("/api/face-studio/gestures", json=body).get_json()["id"]
    clock = [0.0]
    face = FaceController(style="friendly", idle=False, clock=lambda: clock[0])
    assert face.do(key)
    clock[0] = 1
    assert ImageChops.difference(image, face.frame_image()).getbbox() is None


def test_invalid_gesture_does_not_stop_existing_worker(client):
    client.post("/api/face-studio/runtime/play", json={"sink": "null"})
    wait_for(lambda: face_anim.STATE["running"])
    worker = face_anim._anim._thr
    result = client.post("/api/face-studio/runtime/play", json={"sink": "null", "gesture_id": "absent"})
    assert result.status_code == 400
    assert worker.is_alive()
    assert face_anim._anim._thr is worker


def test_slow_tempo_keeps_full_authored_timeline(client):
    body = {"name": "Slow", "duration": 10, "tempo": 0.5, "at": 20}
    assert client.post("/api/face-studio/frame", json=body).status_code == 200
