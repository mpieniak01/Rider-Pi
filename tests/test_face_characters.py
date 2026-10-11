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


@pytest.mark.parametrize("skin", ["human", "cat", "robot"])
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
    face = FaceController(style="friendly", idle=False, clock=lambda: clock[0])
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
