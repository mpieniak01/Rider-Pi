"""Boundary tests for packets 23–24 use fake devices, players and transports only."""

import io
import socket
import threading
from types import SimpleNamespace

import pytest

from apps.compute.runners import wav_bytes
from apps.ui import manager, overlay
from apps.ui.face import schema
from apps.ui.face.controller import FaceController
from apps.ui.status_panel import StatusPanelLifecycle
from common import bus, nlu_shared, test_sandbox
from common.snap import Snapper
from services.audio_playback import PlaybackManager


def segment(**changes):
    return {"t0": 0, "t1": 1, "v0": -1, "v1": 1, **changes}


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"initial": {"unknown": True}, "tracks": {"unknown": []}}, "invalid_field"),
        ({"initial": {"brows.lift": True}}, "invalid_number"),
        ({"tracks": {"unknown": []}}, "invalid_track"),
        ({"tracks": {"brows.lift": [None]}}, "invalid_segment"),
        ({"tracks": {"brows.lift": [segment(ease=[])]}}, "invalid_segment"),
        ({"tracks": {"brows.lift": [segment(t1=0)]}}, "invalid_segment"),
        ({"tracks": {"brows.lift": [segment(v1=2)]}}, "value_out_of_range"),
        ({"contract_version": True}, "unsupported_face_contract"),
    ],
)
def test_gesture_rejects_first_invalid_field_without_coercing_booleans(changes, error):
    with pytest.raises(ValueError, match=error):
        schema.validate({"name": "gesture", **changes})


def test_gesture_segment_boundary_order_and_input_copy():
    tracks = [segment(t0=i / 32, t1=(i + 1) / 32) for i in range(32)]
    body = {"name": "  gesture  ", "tracks": {"brows.tilt": tracks}, "initial": {"mouth.curve": 0}}
    result = schema.validate(body)
    assert result["name"] == "gesture"
    assert len(result["tracks"]["brows.tilt"]) == 32
    result["tracks"]["brows.tilt"][0]["v0"] = 0
    assert tracks[0]["v0"] == -1
    with pytest.raises(ValueError, match="invalid_track"):
        schema.validate({**body, "tracks": {"brows.tilt": tracks + [segment()]}})
    with pytest.raises(ValueError, match="value_out_of_range"):
        schema.validate({**body, "tracks": {"brows.tilt": [segment(t1=0.75), segment(t0=0.5)]}})
    with pytest.raises(KeyError, match="v1"):
        schema.validate({**body, "tracks": {"brows.tilt": [{"t0": 0, "t1": 1, "v0": 0}]}})


def test_renderer_copy_cache_and_professional_background_invalidation():
    controller = FaceController(clock=lambda: 100, idle=False)
    renderer = controller.renderer
    renderer.style, renderer.skin = "minimal", "professional"
    image = renderer.render_image(controller.anim.state)
    original = image.tobytes()
    image.paste((255, 0, 255), (0, 0, image.width, image.height))
    assert renderer.render_image(controller.anim.state).tobytes() == original
    assert renderer.render_count == 1
    first_background = renderer._background
    assert renderer.render_png_bytes(controller.anim.state).startswith(b"\x89PNG")
    assert renderer.render_png_bytes(controller.anim.state).startswith(b"\x89PNG")
    assert renderer.encode_count == 1
    renderer.style = "friendly"
    renderer.render_image(controller.anim.state)
    assert renderer._background is not first_background
    assert renderer.render_count == 2
    assert renderer._background.size == (renderer.size, renderer.size)


def display_fixture(mode="xgo"):
    display = object.__new__(manager.DisplayCtl)
    display.mode, display._power = mode, 1
    display._xgo_lcd = SimpleNamespace()
    display._set_bl = None
    display._xgo_size = (3, 2)
    return display


def test_display_power_records_only_success_and_duplicate_state_has_no_io(monkeypatch):
    display = display_fixture()
    calls = []
    monkeypatch.setattr(display, "_set_xgo_power", lambda on: calls.append(on) or False)
    display.set_power(False)
    assert display._power == 1
    monkeypatch.setattr(display, "_set_xgo_power", lambda on: calls.append(on) or True)
    display.set_power(False)
    display.set_power(False)
    assert display._power == 0
    assert calls == [False, False]


def test_display_black_frame_fallback_and_failed_backlight_do_not_mix(monkeypatch):
    display = display_fixture()
    frames = []
    display._xgo_lcd.ShowImage = lambda frame: frames.append(frame.copy())
    assert display._set_xgo_power(False) is True
    assert frames[0].getpixel((0, 0)) == (0, 0, 0)
    assert display._set_xgo_power(True) is False
    display._set_bl = object()
    monkeypatch.setattr(display, "_bl_set_safe", lambda *_, **__: False)
    assert display._set_xgo_power(False) is False
    assert len(frames) == 1


def test_display_fb_control_uses_only_mocked_file_and_retains_failed_state(monkeypatch):
    display = display_fixture("fb")
    writes = []

    class File(io.StringIO):
        def close(self):
            writes.append(self.getvalue())
            super().close()

    monkeypatch.setattr(manager, "open", lambda *args: File(), raising=False)
    display.set_power(False)
    display.set_power(True)
    assert writes == ["1", "0"]

    def fail(*_):
        raise OSError("fixture denied")

    monkeypatch.setattr(manager, "open", fail)
    display.set_power(False)
    assert display._power == 1


def test_idle_policy_keeps_strict_boundaries_and_off_then_wake_order(monkeypatch):
    events = []
    display = SimpleNamespace(
        dim=lambda: events.append("dim") or False,
        set_power=lambda on: events.append(("power", on)),
        ensure_on=lambda: events.append("wake"),
    )
    monkeypatch.setattr(manager, "DIM_SEC", 3)
    monkeypatch.setattr(manager, "OFF_SEC", 10)
    monkeypatch.setattr(manager, "audio_hook", lambda event: events.append(("audio", event)))
    policy = manager._IdleDisplay(display, 0)
    policy.update(3)
    assert events == []
    policy.update(3.01)
    policy.update(10)
    assert events == ["dim", ("audio", "dim")]
    policy.update(10.01)
    policy.update(20)
    assert events[-2:] == [("power", False), ("audio", "off")]
    policy.last_activity = 20
    policy.update(20)
    assert events[-2:] == ["wake", ("audio", "on")]
    assert policy.powered_off is False
    assert policy.dimmed is False


def test_activity_only_real_moving_observation_renews_timestamp(monkeypatch):
    policy = SimpleNamespace(last_activity=1)
    activity = manager._DisplayActivity(policy)
    monkeypatch.setattr(manager.time, "time", lambda: 20)
    monkeypatch.setattr(manager, "display_motion", lambda row: {"moving": row.get("moving")})
    activity.observe(manager.MOTION_T, {"moving": None})
    activity.observe(b"unknown", {"human": True})
    assert policy.last_activity == 1
    activity.observe(manager.MOTION_T, {"moving": True})
    assert policy.last_activity == 20
    policy.last_activity = 2
    activity.observe(manager.VISION_T, {"moving": False, "human": False})
    assert policy.last_activity == 2
    activity.observe(manager.VISION_T, {"human": True})
    assert policy.last_activity == 20
    assert activity.motion == {"moving": True}


def test_draw_control_and_overlay_preserve_explicit_false_and_ignore_unknown_payload():
    sent = []
    control = manager._DrawControl(SimpleNamespace(send_multipart=sent.append))
    control.set(True)
    control.set(False)
    control.set(False)
    assert sent == [[manager.CTRL_T, b'{"draw": false}']]
    state = {}
    assert overlay._receive_overlay(b"unknown", b"invalid-json", state, False) is False
    assert overlay._receive_overlay(overlay.CTRL_T, b'{"draw":false}', state, True) is False
    assert overlay._receive_overlay(overlay.CTRL_T, b"{}", state, False) is True
    overlay._receive_overlay(overlay.MOTION_T, b'{"moving":null}', state, False)
    overlay._receive_overlay(overlay.VISION_T, b'{"human":true}', state, False)
    assert state == {"motion": {"moving": None}, "vision": {"human": True}}


def test_status_idle_rechecks_ownership_after_releasing_own_sink():
    events = []
    now = SimpleNamespace(value=0)
    owner = {"free": True, "holders": []}
    sink = SimpleNamespace(display=lambda *_, **__: None, rotate=270)

    def release():
        events.append("release")
        owner.update(free=False, holders=[{"pid": -1}])

    sink.close = release
    panel = StatusPanelLifecycle(
        sink_factory=lambda: sink,
        owner_probe=lambda: owner,
        power_off=lambda: events.append("off") or True,
        clock=lambda: now.value,
        idle_s=2,
    )
    panel.step({}, {"ready": False}, "fixture", [])
    now.value = 2
    assert panel.step({}, {"ready": False}, "fixture", []) == "idle_off_unconfirmed"
    assert events == ["release"]
    assert panel.off_confirmed is False


@pytest.mark.parametrize(
    "frames,expected",
    [
        ([], ("", None)),
        ([b'{"value":0}'], ("", {"value": 0})),
        ([b"  legacy.topic {\"value\":0}"], ("legacy.topic", {"value": 0})),
        ([b"topic", b"ignored", b"[0,false]"], ("topic", [0, False])),
        ([b"topic", b"broken"], ("topic", None)),
        ([None, {"value": 0}], ("", {"value": 0})),
        ([b"topic", '{"value":0}'], ("topic", {"value": 0})),
    ],
)
def test_bus_receive_decodes_last_frame_without_real_transport(frames, expected):
    subscriber = object.__new__(bus.BusSub)
    subscriber.sock = SimpleNamespace(recv_multipart=lambda: frames)
    assert subscriber.recv() == expected


def test_bus_timeout_does_not_receive():
    subscriber = object.__new__(bus.BusSub)
    subscriber.sock = SimpleNamespace(
        poll=lambda **_: 0, recv_multipart=lambda: pytest.fail("timeout must not receive")
    )
    assert subscriber.recv(timeout_ms=0) == (None, None)


@pytest.mark.parametrize(
    "bpp,data,expected", [(24, bytes([1, 2, 3]), [1, 2, 3]), (32, bytes([4, 5, 6, 99]), [4, 5, 6])]
)
def test_framebuffer_conversion_preserves_existing_bgr_and_ignores_alpha(bpp, data, expected):
    snapper = object.__new__(Snapper)
    assert snapper._framebuffer_bgr(data, 1, 1, bpp).tolist() == [[expected]]


@pytest.mark.parametrize("data,bpp,expected", [(b"\0", 24, False), (b"\0\0\0", 24, True), (b"\0", 8, False)])
def test_framebuffer_short_read_and_unsupported_depth_never_save(monkeypatch, data, bpp, expected):
    snapper = object.__new__(Snapper)
    snapper.fb_dev, snapper.fb_w, snapper.fb_h, snapper.fb_bpp = "inert-frame", 1, 1, bpp
    snapper._should = lambda _: True
    saved = []
    snapper._save = lambda tag, frame: saved.append((tag, frame.tolist())) or True
    monkeypatch.setattr("common.snap.open", lambda *_: io.BytesIO(data), raising=False)
    assert snapper.lcd_from_fb() is expected
    assert bool(saved) is expected


@pytest.mark.parametrize("text", ["naprzód", "jedź do przedu", "jedź na przód"])
def test_shared_nlu_literal_extraction_preserves_forward_and_stop_precedence(text):
    assert nlu_shared.parse_motion_intent(text)["action"] == "forward"
    assert nlu_shared.parse_motion_intent("stop " + text) == {"action": "stop"}


@pytest.mark.parametrize("path", ["/dev/ttyAMA0", b"/dev/serial0", "/dev/spidev0.0", "/dev/gpiochip0"])
def test_device_guards_reject_before_calling_original(path):
    with pytest.raises(test_sandbox.IsolationError):
        test_sandbox._check_device(path)


def test_socket_guard_calls_original_only_for_permitted_local_fixture():
    calls = []
    guarded = test_sandbox._socket_address_guard(lambda sock, address: calls.append(address) or 0)
    sock = SimpleNamespace(family=socket.AF_INET)
    with pytest.raises(test_sandbox.IsolationError):
        guarded(sock, ("192.0.2.14", 8080))
    with pytest.raises(test_sandbox.IsolationError):
        guarded(sock, ("localhost", 5555))
    assert calls == []
    assert guarded(sock, ("localhost", 32768)) == 0
    assert calls == [("localhost", 32768)]


@pytest.mark.parametrize(
    "argv,options",
    [
        (["git", "push", "https://example.invalid/repo"], {}),
        (["git", "commit"], {"cwd": "/home/pi/Rider-Pi"}),
        (["sh", "-c", "true"], {}),
        (["systemctl", "restart", "fixture.service"], {}),
        (["fuser", "-k", "fixture"], {}),
        (["ffmpeg", "-i", "https://example.invalid/media"], {}),
        (["python3", "-I", "-c", "pass"], {}),
        (["ls"], {"shell": True}),
    ],
)
def test_subprocess_guard_blocks_before_mock_runner(argv, options):
    guarded = test_sandbox._popen_guard(lambda *_, **__: pytest.fail("forbidden runner"), {})
    with pytest.raises(test_sandbox.IsolationError):
        guarded(argv, **options)


def test_fixture_git_redirect_and_child_environment_guards(monkeypatch, tmp_path):
    monkeypatch.setenv("RIDER_TEST_GIT_ROOT", str(tmp_path))
    test_sandbox._validate_git_operation(["git", "commit", "--allow-empty"], "git", tmp_path)
    for args in (["-C", str(tmp_path), "commit"], ["-c", "x.y=z", "commit"], ["config", "--global", "x.y"]):
        with pytest.raises(test_sandbox.IsolationError):
            test_sandbox._validate_git_mutation(args, "commit", tmp_path)
    calls = []
    guarded = test_sandbox._popen_guard(
        lambda *a, **k: calls.append((a, k)), {"MOTION_ENABLE": "0", "PYTHONPATH": "inert"}
    )
    guarded(["python3", "-c", "pass"], env={"MOTION_ENABLE": "1", "OTHER": "kept"})
    assert calls[0][1]["env"]["MOTION_ENABLE"] == "0"
    assert calls[0][1]["env"]["PYTHONPATH"] == "inert"
    assert calls[0][1]["env"]["OTHER"] == "kept"


@pytest.mark.parametrize(
    "mode,state,code",
    [
        ("played", "played", 200),
        ("failed", "failed", 503),
        ("raise", "failed", 503),
        ("cancel", "cancelled", 409),
        ("expire", "expired", 409),
    ],
)
def test_playback_fake_player_result_cancellation_and_release(mode, state, code):
    now = SimpleNamespace(value=10)

    def player(*_, stop_event, **__):
        if mode == "raise":
            raise RuntimeError("fixture")
        if mode in {"cancel", "expire"}:
            if mode == "expire":
                now.value = 12
            stop_event.set()
        return mode == "played"

    manager = PlaybackManager(player=player, config=object(), clock=lambda: now.value)
    data = wav_bytes(b"\0\0" * 320, 16000)
    result, status = manager.execute(data, "fixture", 11)
    assert status == code
    assert result["state"] == state
    assert manager.active is None
    assert manager.done.is_set()
    assert manager.close() is True
    cached, cached_status = manager.execute(data, "fixture", 20)
    assert cached["idempotent"] is True
    assert cached_status == (200 if state == "played" else 409)


def test_playback_expire_only_sets_stop_when_timer_not_completed():
    manager = PlaybackManager(clock=lambda: 10)
    stop = threading.Event()
    finished = SimpleNamespace(wait=lambda delay: delay == 0)
    manager._expire(stop, finished, 9)
    assert stop.is_set() is False
    manager._expire(stop, finished, 11)
    assert stop.is_set() is True


def test_shared_nlu_keeps_legacy_sequential_replacement_edge_case():
    # Existing sequential substring replacement is characterized, not repaired here.
    assert nlu_shared.norm("idź do przodu") == "do przoduu"
    assert nlu_shared.parse_motion_intent("idź do przodu") is None
