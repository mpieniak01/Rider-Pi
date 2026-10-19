"""Issue309 regressions use inert script definitions, images and fake clocks only."""

from __future__ import annotations

import ast
import builtins
import copy
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image, ImageDraw

from apps.compute.client import ComputeError
from apps.compute.navigation import NavigationRunner
from apps.draw.face_primitives import draw_face
from apps.navigator.quality import NavigationQuality
from apps.ui.face.controller import FaceController
from apps.ui.face.model import FaceState
from apps.ui.face.renderer import FaceRenderer

ROOT = Path(__file__).resolve().parents[1]


def script_definitions(relative, names, **scope):
    path = ROOT / relative
    tree = ast.parse(path.read_text())
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in functions} == names
    future = ast.parse("from __future__ import annotations").body
    exec(compile(ast.Module(body=future + functions, type_ignores=[]), str(path), "exec"), scope)
    return scope


def test_all_executed_acks_are_removed_without_clock_checks_or_live_iteration():
    runner = SimpleNamespace(
        pending_motion_acks={"first": 0.0, "second": 0.0},
        motion_failure=None,
        clock=Mock(side_effect=AssertionError("executed ACK takes precedence over deadline")),
    )
    safety = {
        "last_ack": {"request_id": "first", "status": "executed", "accepted": True},
        "recent_acks": [{"request_id": "second", "status": "executed", "accepted": True}],
    }
    NavigationRunner._check_pending_acks(runner, safety)
    assert runner.pending_motion_acks == {}
    assert runner.motion_failure is None
    runner.clock.assert_not_called()


def test_ack_timeout_preserves_order_and_does_not_consume_later_executed_acks():
    runner = SimpleNamespace(
        pending_motion_acks={"done": 0.0, "timed-out": 10.0, "later": 0.0},
        motion_failure=None,
        clock=lambda: 10.0,
    )
    safety = {
        "recent_acks": [
            {"request_id": request_id, "status": "executed", "accepted": True} for request_id in ("done", "later")
        ]
    }
    with pytest.raises(ComputeError, match="navigation_motion_ack_timeout"):
        NavigationRunner._check_pending_acks(runner, safety)
    assert runner.pending_motion_acks == {"timed-out": 10.0, "later": 0.0}
    assert runner.motion_failure == {"http_status": 504, "reason": "navigation_motion_ack_timeout"}


@pytest.mark.parametrize("accepted,status", [(1, "executed"), (False, "executed"), (True, "accepted")])
def test_incomplete_ack_never_becomes_executed_evidence(accepted, status):
    now = [4.9]
    runner = SimpleNamespace(pending_motion_acks={"request": 5.0}, motion_failure=None, clock=lambda: now[0])
    safety = {"last_ack": {"request_id": "request", "status": status, "accepted": accepted}}
    NavigationRunner._check_pending_acks(runner, safety)
    assert runner.pending_motion_acks == {"request": 5.0}
    now[0] = 5.0
    with pytest.raises(ComputeError, match="navigation_motion_ack_timeout"):
        NavigationRunner._check_pending_acks(runner, safety)
    assert runner.pending_motion_acks == {"request": 5.0}


@pytest.mark.parametrize("error", [None, "stale_obstacle_sample"])
def test_private_navigation_gate_stays_fail_closed_without_requested_axes(error):
    failures = []
    quality = SimpleNamespace(
        navigation_quality=lambda: {"data_error": error},
        _quality_failure=lambda reason, **fields: failures.append((reason, fields)),
    )
    assert NavigationQuality._motion_data_permitted(quality) is False
    assert failures == [(error or "navigation_traversal_unverified", {"stop": True})]


def test_forced_binding_only_selects_callable_without_frame_or_invoking_driver():
    push = Mock(side_effect=AssertionError("binding must not transmit a frame"))
    target = SimpleNamespace(present=push)
    sink = SimpleNamespace(force="present:pil", _push=None, _targets=lambda: [target])
    scope = script_definitions("scripts/dev_face-lcd-direct.py", {"_force_bind"})
    assert scope["_force_bind"](sink) is True
    assert sink._push == (target, "present", "pil")
    push.assert_not_called()


@pytest.mark.parametrize("force,targets", [("", None), ("missing:pil", [SimpleNamespace(missing=3)])])
def test_unavailable_force_binding_does_not_claim_driver(force, targets):
    probe = Mock(return_value=targets)
    sink = SimpleNamespace(force=force, _push=None, _targets=probe)
    scope = script_definitions("scripts/dev_face-lcd-direct.py", {"_force_bind"})
    assert scope["_force_bind"](sink) is False
    assert sink._push is None
    if not force:
        probe.assert_not_called()


@pytest.fixture
def mood(monkeypatch):
    monkeypatch.setenv("FACE_TRANS_STEP_S", "0.35")
    monkeypatch.setenv("FACE_TRANS_DWELL_S", "0.18")
    monkeypatch.delenv("FACE_MOUTH_SHAPE", raising=False)
    monkeypatch.delenv("FACE_MOUTH_OPEN", raising=False)
    now = SimpleNamespace(value=0.0)

    def create(style="friendly"):
        face = FaceController(style=style, idle=False, clock=lambda: now.value)
        face.set_mood("happy")
        now.value = 0.35
        face._tick()
        assert face.is_mood_idle()
        return face, now

    return create


@pytest.mark.parametrize("style", ["friendly", "legacy"])
def test_default_crossing_reaches_neutral_holds_then_finishes_target(mood, style):
    face, now = mood(style)
    face.set_mood("sad")
    assert face.anim.state.expr == "neutral"
    assert face.anim.state.mouth.shape == "neutral"
    assert not face.is_mood_idle()
    now.value = 0.7
    neutral = copy.deepcopy(face._tick())
    assert neutral.brows.lift == pytest.approx(0)
    assert neutral.brows.tilt == pytest.approx(0)
    if style == "friendly":
        assert neutral.mouth.curve == pytest.approx(0.15)
    now.value = 0.8
    held = face._tick()
    assert asdict(held.brows) == asdict(neutral.brows)
    assert held.mouth.curve == neutral.mouth.curve
    assert held.expr == "neutral"
    now.value = 0.88
    assert face._tick().expr == "sad"
    assert not face.is_mood_idle()
    now.value = 1.23
    target = face._tick()
    assert target.mouth.shape == "sad"
    assert target.brows.tilt == pytest.approx(-0.35)
    if style == "friendly":
        assert target.mouth.curve == pytest.approx(-0.65)
    assert face.is_mood_idle()


def test_direct_false_keeps_single_step_even_with_configured_dwell(mood, monkeypatch):
    face, now = mood()
    monkeypatch.setenv("FACE_TRANS_DWELL_S", "5")
    face.set_mood("sad", via_neutral=False)
    assert face.anim.state.expr == "sad"
    now.value = 0.525
    assert face._tick().mouth.curve == pytest.approx(0.075)
    now.value = 0.7
    assert face._tick().mouth.curve == pytest.approx(-0.65)
    assert face.is_mood_idle()
    assert face._mood_pending is None


@pytest.mark.parametrize("dwell,expected", [(None, 0.42), (0, 0), (0.6, 0.6)])
def test_dwell_uses_config_default_or_explicit_zero_and_seconds(mood, monkeypatch, dwell, expected):
    face, now = mood()
    monkeypatch.setenv("FACE_TRANS_DWELL_S", "0.42")
    face.set_mood("sad", dwell_s=dwell)
    now.value = 0.7 + expected + 1e-9
    assert face._tick().expr == "sad"
    assert face.anim.state.mouth.curve == pytest.approx(0.15)
    now.value = 1.05 + expected - 0.001
    face._tick()
    assert not face.is_mood_idle()
    now.value += 0.002
    assert face._tick().mouth.curve == pytest.approx(-0.65)
    assert face.is_mood_idle()


@pytest.mark.parametrize("target", ["happy", "neutral", "curious"])
def test_new_mood_replaces_pending_crossing_without_late_target_revival(mood, target):
    face, now = mood()
    face.set_mood("sad", dwell_s=1)
    now.value = 0.8
    face._tick()
    face.set_mood(target, via_neutral=False)
    now.value = 2.5
    state = face._tick()
    assert state.expr == target
    assert face._mood_current == target
    assert face._mood_pending is None
    assert face.is_mood_idle()


@pytest.mark.parametrize("dwell", [-0.01, float("nan"), float("inf"), 20, True, "0.1"])
def test_invalid_crossing_dwell_rejected_before_pose_or_channel_mutation(mood, dwell):
    face, now = mood()
    before = asdict(face.anim.state)
    with pytest.raises(ValueError):
        face.set_mood("sad", dwell_s=dwell)
    assert asdict(face.anim.state) == before
    assert face._mood_current == "happy"
    assert face.anim.owners == {}
    assert face._mood_pending is None


def test_mood_crossing_preserves_higher_priority_audio_channel(mood):
    face, now = mood()
    face.audio_envelope(0.8)
    face.set_mood("sad", dwell_s=0)
    now.value = 0.43
    assert face._tick().mouth.open == pytest.approx(0.8)
    assert face.anim.owners["mouth.open"] == "audio"
    assert face.anim.owners["brows.tilt"] == "emotion"


@pytest.mark.parametrize("size", [(80, 100), (101, 79)])
@pytest.mark.parametrize("mode", ["RGB", "RGBA"])
def test_aa2x_draws_antialiased_overlay_preserves_size_background_and_opacity(size, mode):
    color = (31, 57, 91) if mode == "RGB" else (31, 57, 91, 255)
    original = Image.new(mode, size, color)
    ImageDraw.Draw(original).rectangle((0, 0, 2, 2), fill="magenta")
    state = FaceState()
    state.render_time = 0
    fast = original.copy()
    result = original.copy()
    draw_face(ImageDraw.Draw(fast), {}, state, guide=False)
    canvas = ImageDraw.Draw(result)
    assert draw_face(canvas, {}, state, guide=False, quality="aa2x") is None
    assert result.size == size
    assert result.mode == mode
    assert result.tobytes() != fast.tobytes()
    assert result.crop((0, 0, 4, 4)).tobytes() == original.crop((0, 0, 4, 4)).tobytes()
    assert len(set(result.getdata()) - set(fast.getdata())) > 20
    if mode == "RGBA":
        assert result.getchannel("A").getextrema() == (255, 255)
    canvas.rectangle((0, 0, 1, 1), fill="red")
    assert result.getpixel((0, 0))[:3] == (255, 0, 0)


def test_aa2x_transparent_background_keeps_alpha_and_draws_guide():
    image = Image.new("RGBA", (120, 160))
    state = FaceState()
    state.render_time = 0
    draw_face(ImageDraw.Draw(image), {}, state, quality="aa2x", guide=True)
    assert image.getpixel((0, 0)) == (0, 0, 0, 0)
    assert image.getchannel("A").getextrema() == (0, 255)
    assert any(0 < pixel[3] < 255 for pixel in image.getdata())
    assert image.getbbox()[0] < 10
    assert image.getbbox()[2] > 110


@pytest.mark.parametrize("quality", ["fast", None, "legacy-unknown"])
def test_default_fast_and_legacy_quality_fallback_have_identical_pixels(quality):
    state = FaceState()
    state.render_time = 0
    expected = Image.new("RGB", (100, 100), (31, 57, 91))
    actual = expected.copy()
    draw_face(ImageDraw.Draw(expected), {}, state)
    draw_face(ImageDraw.Draw(actual), {}, state, quality=quality)
    assert actual.tobytes() == expected.tobytes()


def test_reverse_sad_to_happy_also_uses_default_neutral_crossing(mood):
    face, now = mood()
    face.set_mood("sad", via_neutral=False)
    now.value = 0.7
    face._tick()
    face.set_mood("happy")
    assert face.anim.state.expr == "neutral"
    now.value = 1.05
    assert face._tick().mouth.curve == pytest.approx(0.15)
    now.value = 1.24
    assert face._tick().expr == "happy"
    now.value = 1.59
    assert face._tick().mouth.curve == pytest.approx(0.8)
    assert face.is_mood_idle()


def test_closing_face_cancels_pending_expression_as_well_as_channels(mood):
    face, now = mood()
    face.set_mood("sad", dwell_s=1)
    face.close()
    now.value = 3.0
    assert face._tick().expr == "neutral"
    assert face._mood_pending is None
    assert face.anim.owners == {}


def test_explicit_authored_expression_interrupts_pending_mood_pose(mood):
    face, now = mood()
    face.set_mood("sad", dwell_s=1)
    assert face.do("surprised")
    now.value = 3.0
    assert face._tick().expr == "surprised"
    assert face._mood_pending is None


def test_changing_renderer_quality_invalidates_image_and_png_cache():
    state = FaceState()
    state.render_time = 0
    renderer = FaceRenderer({}, size=100, quality="fast")
    fast = renderer.render_image(state)
    fast_png = renderer.render_png_bytes(state)
    renderer.quality = "aa2x"
    antialiased = renderer.render_image(state)
    aa_png = renderer.render_png_bytes(state)
    assert antialiased.tobytes() != fast.tobytes()
    assert aa_png != fast_png
    assert renderer.render_count == 2
    assert renderer.encode_count == 2
    renderer.quality = "fast"
    assert renderer.render_image(state).tobytes() == fast.tobytes()
    assert renderer.render_png_bytes(state) == fast_png
    assert renderer.render_count == 3


@pytest.mark.parametrize("scale", [1, 2])
def test_supersampling_preserves_fixed_pixel_minima_in_small_speaking_face(monkeypatch, scale):
    from apps.draw import face_primitives as primitives

    canvas = SimpleNamespace(im=SimpleNamespace(size=(48 * scale, 48 * scale)), ellipse=Mock(), rectangle=Mock())
    brow = Mock()
    monkeypatch.setattr(primitives, "_draw_brow", brow)
    state = FaceState()
    state.render_time = 0
    state.eyes.blink = 1
    state.assist_speaking = True
    primitives._draw_face_fast(canvas, {}, state, True, pixel_scale=scale)
    assert canvas.ellipse.call_args_list[0].kwargs["width"] == 2 * scale
    pupil = canvas.ellipse.call_args_list[3].args[0]
    assert pupil[3] - pupil[1] == 2 * scale
    assert brow.call_args.kwargs["stroke"] == 6 * scale
    mouth = canvas.rectangle.call_args.args[0]
    assert mouth[1][1] - mouth[0][1] == 6 * scale


@pytest.mark.parametrize("scale", [1, 2])
def test_supersampling_preserves_minimum_ribbon_thickness(monkeypatch, scale):
    from apps.draw import face_primitives as primitives

    canvas = SimpleNamespace(im=SimpleNamespace(size=(48 * scale, 48 * scale)), ellipse=Mock())
    ribbon = Mock()
    monkeypatch.setattr(primitives, "_draw_brow", Mock())
    monkeypatch.setattr(primitives, "_ribbon_mouth", ribbon)
    monkeypatch.setenv("FACE_MOUTH_SMALL_TH_K_BASE", "0")
    state = FaceState()
    state.render_time = 0
    primitives._draw_face_fast(canvas, {}, state, False, pixel_scale=scale)
    assert ribbon.call_args.args[5] == scale


def test_default_retarget_from_pending_neutral_uses_one_step(mood):
    face, now = mood()
    face.set_mood("sad", dwell_s=1)
    now.value = 0.8
    face._tick()
    face.set_mood("happy")
    assert face._mood_pending is None
    now.value = 1.15
    assert face._tick().expr == "happy"
    assert face.anim.state.mouth.curve == pytest.approx(0.8)
    assert face.is_mood_idle()


def test_first_crossing_uses_visible_expression_not_last_requested_mood(monkeypatch):
    monkeypatch.setenv("FACE_TRANS_STEP_S", "0.35")
    face = FaceController(style="friendly", idle=False, clock=lambda: 0.0)
    assert face.anim.state.expr == "happy"
    face.set_mood("sad", dwell_s=0)
    assert face.anim.state.expr == "neutral"
    assert face._mood_pending == (0.35, "sad")


@pytest.mark.parametrize("modern_namespace", [False, True])
def test_aa2x_resampling_supports_legacy_pillow_namespace(modern_namespace):
    background, filtered, final = object(), object(), object()
    composed = SimpleNamespace(convert=Mock(return_value=final))
    overlay = SimpleNamespace(resize=Mock(return_value=filtered))
    image_api = SimpleNamespace(new=Mock(return_value=overlay), LANCZOS=1, alpha_composite=Mock(return_value=composed))
    if modern_namespace:
        image_api.Resampling = SimpleNamespace(LANCZOS=2)
    canvas = SimpleNamespace(
        _image=SimpleNamespace(size=(20, 30), mode="RGB", convert=Mock(return_value=background), paste=Mock())
    )
    overlay_canvas = object()
    draw_api = SimpleNamespace(Draw=Mock(return_value=overlay_canvas))
    fast = Mock()

    def import_pillow(name, *args, **kwargs):
        return (
            SimpleNamespace(Image=image_api, ImageDraw=draw_api)
            if name == "PIL"
            else builtins.__import__(name, *args, **kwargs)
        )

    scope = script_definitions(
        "apps/draw/face_primitives.py",
        {"_draw_face_antialiased"},
        __builtins__={**vars(builtins), "__import__": import_pillow},
        _draw_face_fast=fast,
    )
    model = object()
    scope["_draw_face_antialiased"](canvas, {}, model, False)
    image_api.new.assert_called_once_with("RGBA", (40, 60))
    fast.assert_called_once_with(overlay_canvas, {}, model, False, pixel_scale=2)
    overlay.resize.assert_called_once_with((20, 30), 2 if modern_namespace else 1)
    image_api.alpha_composite.assert_called_once_with(background, filtered)
    composed.convert.assert_called_once_with("RGB")
    canvas._image.paste.assert_called_once_with(final)
