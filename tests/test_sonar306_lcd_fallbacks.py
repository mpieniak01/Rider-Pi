"""Compile owned LCD script helpers only; no script startup or physical I/O."""

from __future__ import annotations

import ast
import dataclasses
import inspect
import re
from collections import deque
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DIRECT_SCRIPT = "dev_face-lcd-direct.py"
SPLASH_SCRIPT = "sys_splash-info.py"


def _definitions(filename, names, namespace):
    source = ROOT / "scripts" / filename
    tree = ast.parse(source.read_text())
    selected = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    assert len(selected) == len(names)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), "exec"), namespace)
    return namespace


def _direct(names=(), **overrides):
    namespace = {"Image": Image, "inspect": inspect, "dataclasses": dataclasses}
    namespace.update(overrides)
    return _definitions(DIRECT_SCRIPT, {"LCDDirect", *names}, namespace)


def test_direct_initialization_survives_optional_setup_failures_and_finds_nested_size():
    @dataclasses.dataclass
    class Config:
        lcd_rotate: int
        lcd_spi_hz: int
        lcd_bl_pin: int

    calls = []

    class FakeLCD:
        device = SimpleNamespace(WIDTH=3, HEIGHT=5)

        def __init__(self, cfg):
            self.cfg = cfg
            calls.append("construct")

        def begin(self):
            calls.append("begin")
            raise OSError("already initialized")

        def set_spi_speed(self, speed):
            calls.append(("speed", speed))
            raise OSError("speed setter unavailable")

    module = SimpleNamespace(LCDRenderer=FakeLCD, FaceConfig=Config)
    namespace = _direct(
        {"_select_direct_lcd_class"},
        import_face_renderers_from_file_first=lambda: module,
    )
    direct = namespace["LCDDirect"](270, 240, spi_hz=123, bl_pin=88)
    assert calls == ["construct", "begin", ("speed", 123)]
    assert direct._disp_wh == (3, 5)
    assert direct._lcd.cfg.lcd_rotate == 270
    assert direct._lcd.cfg.lcd_spi_hz == 123
    assert direct._lcd.cfg.lcd_bl_pin == 88


def test_direct_class_search_and_zero_argument_constructor_fallback():
    namespace = _direct({"_select_direct_lcd_class"})

    class St77Panel:
        pass

    module = SimpleNamespace(LCDRenderer=None, LCDValue=5, Generic=object(), St77Panel=St77Panel)
    assert namespace["_select_direct_lcd_class"](module) is St77Panel
    direct = namespace["LCDDirect"](0, 240, force="pil")
    assert isinstance(direct._construct_lcd(module, St77Panel), St77Panel)
    invalid_module = SimpleNamespace(LCDValue=5)
    with pytest.raises(RuntimeError, match="Brak klasy"):
        namespace["_select_direct_lcd_class"](invalid_module)


@pytest.mark.parametrize("forced", [False, True])
def test_direct_slow_encoder_selects_presenter_unless_explicitly_forced(forced):
    encode = Mock(return_value=b"rgb")
    namespace = _direct(
        {"_dispatch_direct_frame"},
        _direct_encoder_ms=Mock(return_value=45),
        to_rgb565_bytes=encode,
    )
    direct = namespace["LCDDirect"](0, 2, force="pil")
    direct.force = "raw" if forced else None
    direct._disp_wh = (2, 2)
    target = SimpleNamespace(ShowImage=Mock(), push_rgb565=Mock())
    direct._push = (target, "push_rgb565", "rgb565")
    image = Image.new("RGB", (2, 2), "red")
    used = direct.push(image)
    if forced:
        target.push_rgb565.assert_called_once_with(b"rgb")
        target.ShowImage.assert_not_called()
        encode.assert_called_once_with(image)
        assert used.endswith("push_rgb565[rgb565]")
    else:
        target.ShowImage.assert_called_once_with(image)
        target.push_rgb565.assert_not_called()
        encode.assert_not_called()
        assert used.endswith("ShowImage[pil]")
        assert direct._push == (target, "ShowImage", "pil")


def test_direct_encoder_resize_failure_uses_original_and_controller_png_fallback_decodes():
    original = SimpleNamespace(size=(2, 2), resize=Mock(side_effect=ValueError("cannot resize")))
    bench = Mock(return_value=42)
    namespace = _definitions(
        DIRECT_SCRIPT,
        {"_direct_encoder_ms", "_direct_controller_frame"},
        {"Image": Image, "BytesIO": BytesIO, "_bench_rgb565_encoder": bench},
    )
    assert namespace["_direct_encoder_ms"](original) == 42
    bench.assert_called_once_with(original)
    data = BytesIO()
    Image.new("RGB", (1, 1), (1, 2, 3)).save(data, "PNG")
    controller = SimpleNamespace(
        frame_image=Mock(side_effect=OSError("PIL frame unavailable")), frame=Mock(return_value=data.getvalue())
    )
    image = namespace["_direct_controller_frame"](controller)
    assert image.mode == "RGB"
    assert image.getpixel((0, 0)) == (1, 2, 3)
    controller.frame.assert_called_once_with()


@pytest.mark.parametrize("frames", [0, 1])
def test_direct_pil_loop_honors_limit_or_interrupt_and_always_attempts_close(frames):
    ticks = iter([0.0, 0.1, 0.5])
    sleep = Mock(side_effect=KeyboardInterrupt)
    controller = SimpleNamespace(close=Mock(side_effect=OSError("close unavailable")))
    image = Image.new("RGB", (2, 2))
    encode = Mock(return_value=b"png")
    namespace = _definitions(
        DIRECT_SCRIPT,
        {"_run_pil_frames", "_direct_frame_stats"},
        {
            "time": SimpleNamespace(time=lambda: next(ticks), sleep=sleep),
            "_advance_direct_mood": lambda *_args: float("inf"),
            "_direct_controller_frame": Mock(return_value=image),
            "to_png_bytes": encode,
        },
    )
    args = SimpleNamespace(secs=0 if frames == 0 else None, fps=0, stats=True)
    namespace["_run_pil_frames"](controller, args, deque(), 1, float("inf"))
    assert encode.call_count == frames
    assert sleep.call_count == frames
    if frames:
        sleep.assert_called_once_with(1.0)
    controller.close.assert_called_once_with()


def test_direct_cleanup_continues_across_failed_methods_and_objects():
    calls = []

    def failed_close():
        calls.append("device.close")
        raise OSError("closed")

    device = SimpleNamespace(close=failed_close, cleanup=lambda: calls.append("device.cleanup"))
    controller = SimpleNamespace(
        close=lambda: calls.append("controller.close"), off=lambda: calls.append("controller.off")
    )
    namespace = _definitions(DIRECT_SCRIPT, {"_close_direct_devices"}, {})
    namespace["_close_direct_devices"](SimpleNamespace(_lcd=device), controller)
    assert calls == ["device.close", "device.cleanup", "controller.close", "controller.off"]


def test_direct_frame_statistics_preserve_interval_and_zero_duration(capsys):
    stats = _definitions(DIRECT_SCRIPT, {"_direct_frame_stats"}, {})["_direct_frame_stats"]
    assert stats(SimpleNamespace(stats=False), 5, 0, 0, 1, "PIL") == 0
    assert stats(SimpleNamespace(stats=True), 0.5, 0, 0, 1, "PIL") == 0
    assert stats(SimpleNamespace(stats=True), 2, 0, 2, 3, "PIL") == 2
    assert "frames=3 fps~0.0 via PIL" in capsys.readouterr().out


@pytest.mark.parametrize(
    "helper,output,expected",
    [
        ("_ipv4_from_route", "1.1.1.1 via 192.0.2.1 src 192.0.2.8 uid 1000", "192.0.2.8"),
        ("_ipv4_from_route", "local 1.1.1.1 src 127.0.0.1", None),
        ("_ipv4_from_hostname", "not-an-ip 127.0.0.1 192.0.2.9", "192.0.2.9"),
        ("_ipv4_from_hostname", "127.0.0.1 invalid", None),
        ("_ipv4_from_brief", "\nlo UNKNOWN 127.0.0.1/8\neth0 UP 127.0.0.2/8 192.0.2.10/24", "192.0.2.10"),
        ("_ipv4_from_brief", "eth0 DOWN\nlo UNKNOWN 127.0.0.1/8", None),
    ],
)
def test_splash_ip_sources_parse_only_non_loopback_candidates(helper, output, expected):
    query, log = Mock(return_value=output), Mock()
    namespace = _definitions(
        SPLASH_SCRIPT,
        {helper},
        {"subprocess": SimpleNamespace(check_output=query, DEVNULL=-3), "re": re, "_log": log},
    )
    assert namespace[helper]() == expected
    assert query.call_count == 1
    assert query.call_args.kwargs == {"text": True, "stderr": -3}
    assert log.call_count == int(expected is not None)


@pytest.mark.parametrize("backend,failed", [("xgo", False), ("xgo", True), ("pygame", False), ("pygame", True)])
def test_splash_logo_preserves_success_delay_and_contains_backend_failure(backend, failed):
    image = Image.new("RGB", (2, 2))
    show = Mock(side_effect=OSError("display unavailable") if failed else None)
    sleep, log = Mock(), Mock()
    namespace = _definitions(
        SPLASH_SCRIPT,
        {"_show_xgo_logo", "_show_pygame_logo"},
        {
            "_load_logo_for_target": lambda _size: image,
            "SPLASH_LOGO": "fake-logo",
            "SPLASH_LOGO_SECONDS": 0.25,
            "time": SimpleNamespace(sleep=sleep),
            "_log": log,
        },
    )
    if backend == "xgo":
        namespace["_show_xgo_logo"](SimpleNamespace(present_device=show), (2, 2))
        show.assert_called_once_with(image)
    else:
        surface = object()
        pygame = SimpleNamespace(
            image=SimpleNamespace(fromstring=Mock(return_value=surface)), display=SimpleNamespace(update=Mock())
        )
        namespace["_show_pygame_logo"](pygame, SimpleNamespace(blit=show), (2, 2))
        show.assert_called_once_with(surface, (0, 0))
    if failed:
        sleep.assert_not_called()
        assert log.call_args.args == (f"logo show failed ({backend}): display unavailable",)
    else:
        sleep.assert_called_once_with(0.25)
        assert f"logo shown ({backend})" in log.call_args.args[0]


def test_splash_info_rotates_then_resizes_for_actual_target():
    image = Image.new("RGB", (4, 2))
    draw = Mock(return_value=image)
    sink = SimpleNamespace(present_device=Mock())
    namespace = _definitions(
        SPLASH_SCRIPT,
        {"_present_xgo_info"},
        {
            "draw_splash_with": draw,
            "maybe_rotate": lambda img: img.transpose(Image.Transpose.ROTATE_90),
            "Image": Image,
            "WIDTH": 4,
            "HEIGHT": 2,
        },
    )
    info = {"IP": "192.0.2.1"}
    namespace["_present_xgo_info"](sink, info, (3, 5))
    draw.assert_called_once_with(info, 4, 2)
    assert sink.present_device.call_args.args[0].size == (3, 5)
