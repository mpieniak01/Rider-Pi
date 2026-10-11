"""Pure face behaviour tests; no LCD, services, bus or real audio."""

import random
from io import BytesIO

import pytest
from PIL import Image

from apps.ui.face.animator import PATHS, Animator
from apps.ui.face.controller import FaceController
from apps.ui.face.model import FaceState
from apps.ui.face.renderer import FaceRenderer
from apps.ui.face.schema import prepare


def track(value, duration=1):
    return {
        "name": "test",
        "duration": duration,
        "tracks": {"eyes.dx": [{"t0": 0, "t1": duration, "v0": 0, "v1": value, "ease": "lin"}]},
    }


def test_replacement_starts_from_current_pose():
    clock = [0]
    anim = Animator(clock=lambda: clock[0])
    anim.start(track(1))
    clock[0] = 0.5
    assert anim.tick().eyes.dx == 0.5
    anim.start(track(-1))
    assert anim.tick().eyes.dx == 0.5
    clock[0] = 1
    assert anim.tick().eyes.dx == -0.25


def test_priority_and_bounded_channels():
    clock = [0]
    anim = Animator(clock=lambda: clock[0])
    anim.start(track(1), prio=20, owner="operator")
    anim.start(track(-1), prio=1, owner="idle")
    clock[0] = 0.5
    assert anim.tick().eyes.dx == 0.5
    assert anim.owners == {"eyes.dx": "operator"}
    for _ in range(1000):
        anim.start(track(0.2), prio=20)
    assert len(anim.owners) <= len(PATHS)


def test_skipped_segments_and_gaps_hold_correct_values():
    clock = [0]
    anim = Animator(clock=lambda: clock[0])
    spec = {
        "duration": 1,
        "initial": {"eyes.dx": 0.2},
        "tracks": {
            "eyes.dx": [
                {"t0": 0.1, "t1": 0.2, "v0": 0.2, "v1": 0.7},
                {"t0": 0.8, "t1": 1, "v0": 0.7, "v1": 0},
            ]
        },
    }
    anim.start(spec, mode="replace")
    assert anim.tick().eyes.dx == 0.2
    clock[0] = 0.6
    assert anim.tick().eyes.dx == 0.7
    clock[0] = 3
    assert anim.tick().eyes.dx == 0
    assert not anim.busy


def test_png_is_not_on_frame_image_path(monkeypatch):
    controller = FaceController(style="friendly", idle=False)
    monkeypatch.setattr(controller.renderer, "render_png_bytes", lambda *_: pytest.fail("PNG on LCD path"))
    assert controller.frame_image().size == (240, 240)
    assert controller.renderer.encode_count == 0


@pytest.mark.parametrize("style", ["friendly", "minimal", "legacy"])
def test_image_png_and_cache_are_consistent(style):
    state = FaceState()
    state.render_time = 0
    renderer = FaceRenderer({}, style=style)
    image = renderer.render_image(state)
    png = renderer.render_png_bytes(state)
    assert Image.open(BytesIO(png)).convert("RGB").tobytes() == image.tobytes()
    image.paste((255, 0, 0), (0, 0, 240, 240))
    assert renderer.render_png_bytes(state) == png
    assert renderer.render_count == 1
    assert renderer.encode_count == 1


def test_mood_morph_and_audio_own_different_channels(monkeypatch):
    monkeypatch.setenv("FACE_TRANS_STEP_S", "0.35")
    clock = [0]
    controller = FaceController(style="friendly", idle=False, clock=lambda: clock[0])
    controller.anim.state.mouth.curve = 0
    controller.set_mood("happy")
    clock[0] = 0.175
    controller.frame_image()
    assert controller.anim.state.mouth.curve == pytest.approx(0.4)
    controller.audio_envelope(0.8)
    controller.do("surprised")
    clock[0] += 0.08
    controller.frame_image()
    assert controller.anim.state.mouth.open == pytest.approx(0.8)
    assert controller.anim.owners["mouth.open"] == "audio"
    clock[0] += 0.30
    controller.frame_image()
    clock[0] += 0.14
    controller.frame_image()
    assert controller.anim.state.mouth.open == 0


def test_speaking_without_audio_does_not_fake_mouth_motion():
    controller = FaceController(style="friendly", idle=False)
    controller.speak(True)
    controller.frame_image()
    assert controller.anim.state.mouth.open == 0


def test_seeded_gaze_is_repeatable():
    frames = []
    for _ in range(2):
        clock = [0]
        controller = FaceController(
            style="friendly", idle=False, clock=lambda clock=clock: clock[0], rng=random.Random(7)
        )
        controller.do("look")
        clock[0] = 0.25
        frames.append(controller.frame_image().tobytes())
    assert frames[0] == frames[1]


def test_tempo_intensity_do_not_mutate_original():
    original = track(0.8)
    prepared = prepare(original, intensity=0.5, tempo=2)
    assert prepared["duration"] == 0.5
    assert prepared["tracks"]["eyes.dx"][0]["v1"] == 0.4
    assert original["tracks"]["eyes.dx"][0]["v1"] == 0.8


def test_replace_static_pose_takes_channel_from_previous_animation():
    clock = [0.0]
    anim = Animator(clock=lambda: clock[0])
    anim.start({"duration": 1, "initial": {"eyes.dx": 0.9}})
    clock[0] = 0.2
    anim.start({"duration": 1, "initial": {"eyes.dx": -0.4}}, mode="replace")
    clock[0] = 0.8
    assert anim.tick().eyes.dx == -0.4


def test_idle_blink_returns_to_sleepy_resting_eyelids(monkeypatch):
    monkeypatch.setenv("FACE_BLINK_SHIFT_PROB", "0")
    clock = [0.0]
    face = FaceController(style="friendly", idle=False, clock=lambda: clock[0])
    face.anim.state.eyes.blink = 0.65
    assert face.do("blink", priority=1, owner="idle")
    clock[0] = 1
    assert face.frame_image()
    assert face.anim.state.eyes.blink == 0.65


def test_small_rounded_shapes_use_integer_bounds_for_cm4_pillow():
    from apps.ui.face.friendly import _rounded

    class Canvas:
        def rounded_rectangle(self, box, *, radius, fill):
            assert all(type(value) is int for value in box)
            assert type(radius) is int
            assert radius * 2 <= box[3] - box[1]
            assert radius * 2 <= box[2] - box[0]

    for height in (5.1, 5.9, 6.2, 20.7):
        _rounded(Canvas(), (96.4, 174.2 - height / 2, 143.6, 174.2 + height / 2), height / 2, "white")
