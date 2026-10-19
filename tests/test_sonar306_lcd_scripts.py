"""LCD script contracts compile selected definitions; no script initialization or device I/O."""

from __future__ import annotations

import ast
import dataclasses
import inspect
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def definitions(filename, names, namespace):
    tree = ast.parse((ROOT / "scripts" / filename).read_text())
    selected = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    assert len(selected) == len(names)
    exec(compile(ast.Module(body=selected, type_ignores=[]), filename, "exec"), namespace)
    return namespace


@pytest.mark.parametrize("requires_fields", [False, True])
def test_clean_lcd_instantiates_after_both_face_config_constructor_paths(requires_fields):
    if requires_fields:

        @dataclasses.dataclass
        class Config:
            lcd_rotate: int
    else:

        @dataclasses.dataclass
        class Config:
            lcd_rotate: int = 0

    class FakeLCD:
        def __init__(self, config):
            self.config = config
            self.width, self.height = 240, 320
            self.device = SimpleNamespace(SPI=SimpleNamespace(max_speed_hz=0))

    namespace = definitions(
        "dev_face-lcd-clean.py",
        {"_build_lcd", "_construct_clean_lcd", "_clean_face_config"},
        {
            "dataclasses": dataclasses,
            "os": SimpleNamespace(getenv=lambda key, default: {"FACE_LCD_SPI_HZ": "123"}.get(key, default)),
            "_pick_lcd_class": lambda *_args: FakeLCD,
            "_maybe_faceconfig": lambda _module: Config,
        },
    )
    instance, device, width, height = namespace["_build_lcd"](object(), 270)
    assert isinstance(instance, FakeLCD)
    assert isinstance(instance.config, Config)
    assert instance.config.lcd_rotate == (270 if requires_fields else 0)
    assert device.SPI.max_speed_hz == 123
    assert (width, height) == (240, 320)


def test_clean_raw_push_preserves_window_command_and_chunk_order():
    device = SimpleNamespace(SetWindows=Mock(), command=Mock(), spi_writebyte=Mock())
    namespace = definitions(
        "dev_face-lcd-clean.py",
        {"_write_clean_raw", "_push_clean_frame"},
        {
            "_to_rgb565": lambda *_args, **_kwargs: b"abcde",
            "os": SimpleNamespace(getenv=lambda _key, _default: "2"),
        },
    )
    namespace["_push_clean_frame"](device, None, True, False, object(), False, True, 3, 4)
    device.SetWindows.assert_called_once_with(0, 0, 2, 3)
    device.command.assert_called_once_with(0x2C)
    assert device.spi_writebyte.call_args_list == [call(b"ab"), call(b"cd"), call(b"e")]


@pytest.mark.parametrize(
    "tag,expected",
    [
        ("pil", (("image",), {})),
        ("pil_kw", (("image",), {})),
        ("png", ((b"png",), {})),
        ("png_kw", ((), {"png": b"png"})),
        ("png_kw2", ((), {"frame_png": b"png"})),
        ("rgb565", ((b"rgb",), {})),
        ("rgb565_kw", ((), {"data": b"rgb"})),
        ("rgb565_kw2", ((), {"buf": b"rgb"})),
        ("rgb565_3", ((3, 4, b"rgb"), {})),
    ],
)
def test_direct_dispatch_keeps_bound_encoding_call_shape(tag, expected):
    image = SimpleNamespace(size=(3, 4))
    namespace = definitions(
        "dev_face-lcd-direct.py",
        {"_dispatch_direct_frame"},
        {
            "to_png_bytes": lambda _image: b"png",
            "to_rgb565_bytes": lambda _image: b"rgb",
        },
    )
    method = Mock()
    namespace["_dispatch_direct_frame"](method, tag, image)
    args, kwargs = expected
    args = tuple(image if value == "image" else value for value in args)
    assert method.call_args == call(*args, **kwargs)


def test_direct_probe_records_only_failed_variants_before_binding():
    namespace = definitions("dev_face-lcd-direct.py", {"LCDDirect"}, {"Image": Image})
    direct = object.__new__(namespace["LCDDirect"])
    target = SimpleNamespace()
    attempts = []

    def method(*args, **kwargs):
        attempts.append((args, kwargs))
        if "buf" not in kwargs:
            raise TypeError("try next call shape")

    tried = []
    used = direct._probe_push_variants(target, "present", method, SimpleNamespace(size=(3, 4)), b"png", b"rgb", tried)
    assert used.endswith("present[rgb565_kw2]")
    assert direct._push == (target, "present", "rgb565_kw2")
    assert len(attempts) == 8
    assert len(tried) == 7


@pytest.mark.parametrize("idle,expected_time", [(True, 12), (False, 10.05)])
def test_mood_sequence_only_rotates_when_controller_is_idle(idle, expected_time):
    controller = SimpleNamespace(is_mood_idle=lambda: idle, set_mood=Mock())
    sequence = deque(["happy", "sad"])
    args = SimpleNamespace(mood_via_neutral=True, mood_dwell=0.18)
    namespace = definitions("dev_face-lcd-direct.py", {"_advance_direct_mood"}, {})
    assert namespace["_advance_direct_mood"](controller, args, sequence, 2, 9, 10) == expected_time
    assert list(sequence) == (["sad", "happy"] if idle else ["happy", "sad"])
    assert controller.set_mood.call_count == int(idle)


def test_splash_address_fallback_keeps_order_and_diagnostic_label():
    route = Mock(side_effect=OSError("route unavailable"))
    host = Mock(return_value="192.0.2.1")
    brief = Mock(side_effect=AssertionError("should not query third source"))
    log = Mock()
    namespace = definitions(
        "sys_splash-info.py",
        {"_get_ipv4"},
        {"_ipv4_from_route": route, "_ipv4_from_hostname": host, "_ipv4_from_brief": brief, "_log": log},
    )
    assert namespace["_get_ipv4"]() == "192.0.2.1"
    log.assert_called_once_with("route-get fail: route unavailable")
    brief.assert_not_called()


def test_weather_method_fallback_tries_next_method_after_failure():
    display = SimpleNamespace(ShowImage=Mock(side_effect=OSError("unsupported")), draw=Mock())
    image = object()
    namespace = definitions("demo_weather-lcd.py", {"_send_weather_image"}, {})
    assert namespace["_send_weather_image"](display, ("ShowImage", "show", "draw"), image)
    display.draw.assert_called_once_with(image)


def test_status_summary_retains_missing_service_warning_and_empty_state():
    namespace = definitions(
        "lcd_renderer.py", {"summarize_state", "_active_feature_lines"}, {"source_time": lambda _value: None}
    )
    title, lines, warn = namespace["summarize_state"](
        {
            "active": ["voice"],
            "features": [{"name": "voice", "title": "Voice", "services": [{"active": True}, {"active": False}]}],
        }
    )
    assert title == "Zadania (ostatni zapis)"
    assert lines == ["Voice: brak 1 usług"]
    assert warn is True
    assert namespace["summarize_state"]({}) == ("Stan 0", ["S0 – tylko usługi bazowe"], False)


def test_direct_lcd_loop_renders_one_frame_then_honors_limit_and_cleans_up():
    ticks = iter([0.0, 0.5, 1.0, 1.1])
    close = Mock()
    image = Image.new("RGB", (2, 2))
    lcd = SimpleNamespace(push=Mock(return_value="fake-driver"))
    controller = object()
    namespace = definitions(
        "dev_face-lcd-direct.py",
        {"_run_lcd_frames"},
        {
            "time": SimpleNamespace(time=lambda: next(ticks), sleep=Mock()),
            "_advance_direct_mood": lambda *_args: float("inf"),
            "_direct_controller_frame": lambda _controller: image,
            "_direct_frame_stats": lambda *_args: 0,
            "_close_direct_devices": close,
        },
    )
    args = SimpleNamespace(secs=1.0, fps=20)
    namespace["_run_lcd_frames"](controller, lcd, args, deque(), 2, float("inf"))
    lcd.push.assert_called_once_with(image)
    close.assert_called_once_with(lcd, controller)
    namespace["time"].sleep.assert_called_once_with(0.05)
