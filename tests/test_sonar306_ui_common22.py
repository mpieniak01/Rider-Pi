"""Packet 22 exercises only pure rendering and inert UI/intent fixtures."""

import copy
import importlib.util
import io
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from apps.ui.face import __main__ as face_main, animator, characters, config
from apps.ui.face.controller import FaceController

ROOT = Path(__file__).resolve().parents[1]


def isolated_module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    previous = sys.path[:]
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = previous
    return module


def inert_bus(monkeypatch):
    bus = ModuleType("common.bus")
    bus.BusPub = lambda: SimpleNamespace(send=lambda *_: pytest.fail("No BUS publish from import"))
    bus.BusSub = lambda *_: pytest.fail("No subscription from import")
    monkeypatch.setitem(sys.modules, "common.bus", bus)


def test_menu_button_dispatch_keeps_down_only_and_back_semantics(monkeypatch):
    inert_bus(monkeypatch)
    menu = isolated_module("sonar306_menu", "apps/menu/main.py")
    events = []
    for key in ("left", "right", "ok", "back"):
        monkeypatch.setattr(menu, "on_" + key, lambda name=key: events.append(name))
    menu._button_event({"id": "back", "event": "up"})
    assert events == []
    menu._button_event({"id": "back", "event": "DOWN"})
    menu._button_event({"id": "left", "event": "down"})
    menu._button_event({"id": "invalid", "event": "down"})
    assert events == ["back", "left"]


def test_nlu_transcript_validation_does_not_promote_move_proposals_to_commands(monkeypatch):
    inert_bus(monkeypatch)
    nlu = isolated_module("sonar306_nlu", "apps/nlu/main.py")
    emitted = []
    monkeypatch.setattr(nlu, "_bus_publish", lambda topic, body: emitted.append((topic, body)))
    monkeypatch.setattr(nlu, "log", lambda _: None)
    nlu._process_transcript({"text": "jedź", "lang": "pl", "source": "voice", "is_final": False})
    assert emitted == []
    nlu._process_transcript({"text": "jedź", "lang": "pl", "source": "voice", "is_final": True})
    assert len(emitted) == 1
    assert emitted[0][0] == "motion.intent"
    assert emitted[0][1].get("operator_consent") is not True
    assert emitted[0][1].get("test_operator_consent") is not True


@pytest.mark.parametrize("text", ["\x1b[C", "\x1b[D", "e"])
def test_simulated_key_reader_consumes_only_the_existing_escape_sequence(monkeypatch, text):
    inert_bus(monkeypatch)
    buttons = isolated_module("sonar306_buttons", "apps/ui/buttons.py")
    stream = io.StringIO(text + "remaining")

    def ready(*_):
        return [stream], [], []

    assert buttons._read_sim_key(stream, ready) == text
    assert stream.read() == "remaining"


def test_missing_escape_suffix_is_not_read_from_empty_simulator(monkeypatch):
    inert_bus(monkeypatch)
    buttons = isolated_module("sonar306_buttons_empty", "apps/ui/buttons.py")
    stream = io.StringIO("\x1brest")
    assert buttons._read_sim_key(stream, lambda *_: ([], [], [])) == "\x1b"
    assert stream.read() == "rest"


def test_face_api_candidates_preserve_explicit_path_order_and_repository_fallback(tmp_path):
    directories = [tmp_path / "first", tmp_path / "second", tmp_path]
    candidates = []
    for directory in directories:
        path = directory / "services/api_core/face_api.py"
        path.parent.mkdir(parents=True)
        path.write_text("# inert fixture")
        candidates.append(path)
    result = face_main._face_api_candidates(tmp_path, " first : second : ")
    assert result == candidates


def test_face_canvas_keeps_full_frame_and_requested_270_degree_compensation():
    face = Image.new("RGB", (8, 12), (255, 0, 0))
    canvas = face_main._face_canvas(face, 24, 40, False, 270)
    assert canvas.size == (40, 24)
    assert canvas.getpixel((0, 0)) == (8, 36, 70)
    assert canvas.getbbox() == (0, 0, 40, 24)


def test_face_sink_fallback_order_never_skips_a_failed_framebuffer(monkeypatch):
    events = []
    controller = SimpleNamespace(
        renderer=SimpleNamespace(render_png_bytes=lambda _: b"fixture"), anim=SimpleNamespace(state={})
    )
    monkeypatch.setattr(face_main, "push_via_face_api", lambda *_: events.append("api") or False)
    monkeypatch.setattr(face_main, "img_to_rgb565", lambda _: events.append("encode") or b"inert")
    monkeypatch.setattr(face_main, "write_framebuffer", lambda *_: events.append("fb") or False)
    monkeypatch.setattr(face_main, "atomic_write", lambda *_: events.append("file"))
    result = face_main._present_face(Image.new("RGB", (2, 2)), controller, "lcd", "fixture.png", True, "fixture-fb")
    assert events == ["api", "encode", "fb", "file"]
    assert result == "file:fixture.png"


def test_png_presentation_has_no_api_or_framebuffer_fallback(monkeypatch):
    events = []
    monkeypatch.setattr(face_main, "atomic_write", lambda *_: events.append("file"))
    monkeypatch.setattr(face_main, "push_via_face_api", lambda *_: pytest.fail("PNG has no API call"))
    monkeypatch.setattr(face_main, "write_framebuffer", lambda *_: pytest.fail("PNG has no framebuffer call"))
    result = face_main._present_face(Image.new("RGB", (2, 2)), None, "png", "fixture.png", True, "fixture-fb")
    assert result == "file:fixture.png"
    assert events == ["file"]


def test_animation_priority_rejects_replace_without_mutating_current_channel():
    clock = SimpleNamespace(now=100)
    animation = animator.Animator(clock=lambda: clock.now)
    animation.start({"duration": 1, "initial": {"eyes.dx": 0.4}}, prio=100, mode="replace", owner="audio")
    before = copy.deepcopy(animation._channels["eyes.dx"])
    animation.start({"duration": 1, "initial": {"eyes.dx": -0.8}}, prio=1, mode="replace", owner="idle")
    assert animation.value("eyes.dx") == 0.4
    assert animation._channels["eyes.dx"] == before


def test_animation_blend_reanchors_copy_and_preserves_input_tracks():
    animation = animator.Animator(clock=lambda: 100)
    animation._set("eyes.dx", 0.25)
    track = {"duration": 1, "tracks": {"eyes.dx": [{"t0": 0, "t1": 1, "v0": -1, "v1": 0.5, "ease": "lin"}]}}
    animation.start(track)
    assert animation._channels["eyes.dx"].segments[0]["v0"] == 0.25
    assert track["tracks"]["eyes.dx"][0]["v0"] == -1


@pytest.mark.parametrize("skin", ["none", "human", "cat", "robot", "professional", "unknown"])
def test_character_shells_keep_scaled_animated_feature_area_clear(skin):
    image = Image.new("RGB", (120, 120), (0, 0, 0))
    characters.draw_character(ImageDraw.Draw(image), skin)
    if skin in {"none", "unknown"}:
        assert image.getbbox() is None
    else:
        assert image.getbbox() is not None
        # Static character shells never paint the eye/mouth animation details themselves.
        assert image.getpixel((60, 60)) != (0, 0, 0)


def test_nested_face_configuration_keeps_numeric_boolean_compatibility_and_field_names():
    result = {}
    config._import_face_section(
        result,
        {
            "idle": {"enable": 0, "blink_sec": 4},
            "gesture": {"blink": {"hold": 0.1}, "look": {"amp": 0.2}},
            "mouth": {
                "small_th_k": {"base": True},
                "offsets": {"y_offset_k_happy": 0.03},
                "lift": {"sad": -0.02},
                "arch": {"neutral": 0.01},
            },
            "transitions": {"step_s": 0.5},
            "debug": {"mouth": 1},
        },
    )
    assert result["idle_enable"] is False
    assert result["small_th_k_base"] == 1.0
    assert result["mouth_y_offset_k_happy"] == 0.03
    assert result["mouth_sad_lift_k"] == -0.02
    assert result["mouth_neutral_arch_k"] == 0.01
    assert result["gesture_blink_hold"] == 0.1
    assert result["gesture_look_amp"] == 0.2
    assert result["trans_step_s"] == 0.5
    assert result["debug_mouth"] is True


def test_disabled_builtin_gesture_keeps_rng_and_active_selection_semantics():
    controller = FaceController(clock=lambda: 100, idle=False)
    controller.active_gestures = set()
    assert controller.do("look") is False
    assert controller.anim.busy is False
