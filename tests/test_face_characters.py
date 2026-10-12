"""Character shells stay optional, bounded and shared by preview/runtime."""

from io import BytesIO

import pytest
from PIL import Image, ImageChops

from apps.ui.face.characters import SKINS
from apps.ui.face.controller import FaceController
from apps.ui.face.model import FaceState
from apps.ui.face.renderer import FaceRenderer
from tests.test_face_runtime_settings import client  # noqa: F401


@pytest.mark.parametrize("style", ["friendly", "minimal", "legacy"])
def test_no_character_preserves_default_pixels(style):
    state = FaceState()
    state.render_time = 0
    assert (
        FaceRenderer({}, style=style).render_image(state).tobytes()
        == FaceRenderer({}, style=style, skin="none").render_image(state).tobytes()
    )


@pytest.mark.parametrize("style", ["friendly", "minimal", "legacy"])
def test_each_character_is_distinct_and_uses_one_background(style):
    state = FaceState()
    state.render_time = 0
    renderer = FaceRenderer({}, style=style)
    images = set()
    for skin in SKINS:
        renderer.skin = skin
        image = renderer.render_image(state)
        images.add(image.tobytes())
        background = renderer._background
        state.eyes.blink = 0.5
        renderer.render_image(state)
        assert renderer._background is background
        state.eyes.blink = 0
    assert len(images) == len(SKINS)


def test_changing_only_character_invalidates_image_and_png():
    renderer = FaceRenderer({}, style="friendly")
    state = FaceState()
    plain = renderer.render_png_bytes(state)
    renderer.skin = "human"
    human = renderer.render_png_bytes(state)
    assert plain != human
    assert renderer.render_count == renderer.encode_count == 2
    assert renderer.render_png_bytes(state) == human
    assert renderer.render_count == renderer.encode_count == 2


@pytest.mark.parametrize("skin", ["human", "cat", "robot", "professional"])
def test_character_keeps_animated_features_and_no_png_on_image_path(skin):
    face = FaceController(style="friendly", skin=skin, idle=False)
    resting = face.frame_image()
    face.anim.state.eyes.blink = 1
    closed = face.frame_image()
    face.anim.state.mouth.open = 0.7
    speaking = face.frame_image()
    assert resting.tobytes() != closed.tobytes() != speaking.tobytes()
    assert face.renderer.encode_count == 0
    assert ImageChops.difference(resting, speaking).getbbox() is not None


def test_preview_matches_controller_with_saved_character(client):
    from apps.ui.face import catalog

    before = client.get("/api/face-studio/runtime").get_json()
    saved = client.post("/api/face-studio/runtime", json={"skin": "cat", "if_revision": before["settings_revision"]})
    assert saved.status_code == 200
    assert saved.get_json()["state"]["playing"] is False
    assert catalog.get_settings()["skin"] == "cat"
    descriptors = saved.get_json()["descriptors"]
    assert {row["id"] for row in descriptors["skins"]} == set(SKINS)
    body = {"name": "Happy cat", "expr": "happy", "duration": 1}
    frame = client.post("/api/face-studio/frame", json={**body, "at": 1})
    assert frame.status_code == 200
    key = client.post("/api/face-studio/gestures", json=body).get_json()["id"]
    clock = [0.0]
    face = FaceController(style="friendly", idle=False, clock=lambda clock=clock: clock[0])
    face.configure({**catalog.get_settings(), "active_gestures": [key]})
    assert face.do(key)
    clock[0] = 1
    image = Image.open(BytesIO(frame.data)).convert("RGB")
    assert image.tobytes() == face.frame_image().tobytes()


@pytest.mark.parametrize("skin", ["unknown", None, 3])
def test_invalid_character_does_not_change_settings(client, skin):
    old = client.get("/api/face-studio/runtime").get_json()["settings"]
    assert client.post("/api/face-studio/runtime", json={"skin": skin}).status_code == 400
    assert client.get("/api/face-studio/runtime").get_json()["settings"] == old
    assert client.post("/api/face-studio/frame", json={"name": "Bad", "skin": skin}).status_code == 400


def test_existing_settings_without_character_default_to_none(client):
    from apps.ui.face import catalog

    old = catalog.get_settings()
    old.pop("skin")
    catalog.atomic_write(catalog.settings_path(), old)
    assert catalog.get_settings()["skin"] == "none"


def test_running_worker_loads_skin_change_without_restarting(client):
    from services.api_core import face_anim
    from tests.test_face_runtime_settings import wait_for

    client.post("/api/face-studio/runtime/play", json={"sink": "null"})
    wait_for(lambda: face_anim.STATE["frame_count"] > 0)
    thread = face_anim._anim._thr
    assert client.post("/api/face-studio/runtime", json={"skin": "robot"}).status_code == 200
    wait_for(lambda: face_anim.STATE.get("skin") == "robot", seconds=2)
    assert face_anim._anim._thr is thread
    image = Image.open(BytesIO(client.get("/api/face-studio/runtime/frame").data)).convert("RGB")
    assert image.getpixel((120, 24)) == (113, 190, 203)


@pytest.mark.parametrize("expression", ["neutral", "calm", "happy", "sad", "curious", "surprised", "sleepy"])
def test_professional_supports_each_emotion_and_shared_gestures(expression):
    from apps.ui.face.schema import MOODS

    clock = [0.0]
    face = FaceController(style="friendly", skin="professional", idle=False, clock=lambda clock=clock: clock[0])
    face.set_mood(expression)
    clock[0] = 1
    face.frame_image()
    assert face.anim.state.expr == expression
    for key, value in MOODS[expression].items():
        assert face.anim.value(key) == pytest.approx(value)
    assert face.do("blink")
    assert face.do("look")
    face.audio_envelope(0.6)
    clock[0] += 0.08
    assert face.frame_image().size == (240, 240)
    assert face.anim.state.mouth.open == pytest.approx(0.6)
    assert face.renderer.encode_count == 0


def test_professional_has_seven_distinct_emotion_poses():
    frames = set()
    for expression in ("neutral", "calm", "happy", "sad", "curious", "surprised", "sleepy"):
        clock = [0.0]
        face = FaceController(style="friendly", skin="professional", idle=False, clock=lambda clock=clock: clock[0])
        face.set_mood(expression)
        clock[0] = 1
        frames.add(face.frame_image().tobytes())
    assert len(frames) == 7


def test_professional_static_frame_does_not_depend_on_legacy_clock():
    state = FaceState()
    state.render_time = 0
    renderer = FaceRenderer({}, style="legacy", skin="professional")
    first = renderer.render_image(state)
    background = renderer._background
    state.render_time = 10
    assert renderer.render_image(state).tobytes() == first.tobytes()
    assert renderer._background is background
    assert renderer.render_count == 1
