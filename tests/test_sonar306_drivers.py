"""Packet 21 regressions with inert LCD backends and offline UART data only."""

import builtins
import copy
import importlib.util
import io
import queue
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from drivers import led
from drivers.xgo import protocol
from drivers.xgo.sniffer import Capture
from drivers.xgo.sniffer_analysis import analyze

ROOT = Path(__file__).resolve().parents[1]


def _load_module(monkeypatch, name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def _inert_lcd(monkeypatch):
    gpio = ModuleType("RPi.GPIO")
    gpio.BCM, gpio.OUT, gpio.LOW, gpio.HIGH = (11, 1, 0, 1)
    gpio.calls = []
    for name in ("setmode", "setwarnings", "setup", "output", "cleanup"):
        setattr(gpio, name, lambda *args, _name=name, **kwargs: gpio.calls.append((_name, args, kwargs)))
    rpi = ModuleType("RPi")
    rpi.GPIO = gpio
    spidev = ModuleType("spidev")

    def unexpected_device():
        raise AssertionError("import must not construct SPI")

    spidev.SpiDev = unexpected_device
    for name, module in (("RPi", rpi), ("RPi.GPIO", gpio), ("spidev", spidev), ("xgoscreen", ModuleType("xgoscreen"))):
        monkeypatch.setitem(sys.modules, name, module)
    # Own only a new guard. An installed filter's delegate is already the original
    # print; replacing it with the current (wrapped) print would create a cycle.
    if not hasattr(builtins, "_rider_print_orig"):
        monkeypatch.setattr(builtins, "_rider_print_orig", builtins.print, raising=False)
    _load_module(monkeypatch, "drivers.lcd.ili9xx_device", "drivers/lcd/ili9xx_device.py")
    module = _load_module(monkeypatch, "drivers.lcd.driver_ili9xx", "drivers/lcd/driver_ili9xx.py")
    module.test_gpio = gpio
    return module


@pytest.fixture
def lcd(monkeypatch):
    return _inert_lcd(monkeypatch)


@pytest.mark.parametrize("prior_import", [False, True])
def test_lcd_fixture_preserves_print_delegate_across_imports_and_restoration(monkeypatch, prior_import):
    with monkeypatch.context() as process:
        _inert_lcd(process)
        original_print = builtins._rider_print_orig
        process.setattr(builtins, "print", original_print)
        process.delattr(builtins, "_rider_print_orig")
        if prior_import:
            previous = _load_module(process, "drivers.lcd.driver_ili9xx", "drivers/lcd/driver_ili9xx.py")
            assert builtins.print is previous._rider_print
            assert builtins._rider_print_orig is original_print
        previous_print = builtins.print
        with monkeypatch.context() as fixture:
            _inert_lcd(fixture)
            _load_module(fixture, "drivers.lcd.driver_ili9xx", "drivers/lcd/driver_ili9xx.py")
            assert builtins.print is previous_print
            assert builtins._rider_print_orig is original_print
            output = io.StringIO()
            builtins.print("fixture print", file=output)
            assert output.getvalue() == "fixture print\n"
        assert builtins.print is previous_print
        assert hasattr(builtins, "_rider_print_orig") is prior_import
        output = io.StringIO()
        builtins.print("restored print", file=output)
        assert output.getvalue() == "restored print\n"
        if prior_import:
            assert builtins._rider_print_orig is original_print
            output = io.StringIO()
            builtins.print("[face] path=RAW", file=output)
            assert output.getvalue() == ""


def _environment(monkeypatch, lcd, values):
    monkeypatch.setattr(lcd, "os", SimpleNamespace(getenv=lambda name, default=None: values.get(name, default)))


def test_lcd_public_reexports_and_runtime_constructor_overrides(lcd, monkeypatch):
    device_layer = sys.modules["drivers.lcd.ili9xx_device"]
    assert lcd.LCDRenderer is device_layer.LCDRenderer
    assert lcd.FaceConfig is device_layer.FaceConfig
    assert lcd.LCDRenderer.__module__ == "drivers.lcd.driver_ili9xx"
    assert lcd.LCDBoard is device_layer.LCDBoard
    assert lcd.Callable is device_layer.Callable
    calls = []
    spi = SimpleNamespace(mode=0, max_speed_hz=1)

    class Device:
        width, height = (0, 0)
        lcd = SimpleNamespace(width=2, height=1)
        SPI = spi

        def begin(self):
            calls.append("begin")
            raise ValueError("try next initializer")

        def Init(self):
            calls.append("Init")

    cfg = SimpleNamespace(lcd_do_init=True, lcd_spi_hz=None, lcd_bl_pin=77)
    monkeypatch.setattr(lcd, "FaceConfig", lambda: cfg)
    monkeypatch.setattr(lcd, "_pick_device_class", lambda: Device)
    monkeypatch.setattr(lcd, "_find_presenter", lambda dev: (dev, calls.append))
    monkeypatch.setattr(lcd, "_find_raw_iface", lambda dev: (None, None, None, None))
    _environment(monkeypatch, lcd, {"FACE_LCD_SPI_HZ": "123", "FACE_SPI_MODE": "3"})
    renderer = lcd.LCDRenderer()
    assert renderer.cfg is cfg
    assert renderer.device.SPI is spi
    assert spi.max_speed_hz == 123
    assert spi.mode == 3
    assert calls == ["begin", "Init"]
    assert renderer.width == 2
    assert renderer.height == 1
    assert renderer._bl_pin == 77
    assert lcd.LCDRenderer.push_frame is lcd._force_push_frame
    assert lcd.LCDRenderer.push_rgb565_3 is lcd._raw_push_rgb565_3
    monkeypatch.setattr(lcd, "Image", None)
    with pytest.raises(RuntimeError, match="Pillow"):
        lcd.LCDRenderer()


def test_lcd_discovery_uses_facade_overrides(lcd, monkeypatch):
    module = ModuleType("fake_panel")
    first = type("LCDOne", (), {"__module__": module.__name__})
    second = type("LCDTwo", (), {"__module__": module.__name__})
    module.first, module.second = (first, second)
    monkeypatch.setattr(lcd, "_iter_xgo_modules", lambda: [module])
    monkeypatch.setattr(lcd, "_score_class", lambda cls: int(cls is first))
    assert lcd._pick_device_class() is first
    package = SimpleNamespace(__path__=[], __name__="fake_package")
    nested = ModuleType("fake_package.panel")
    monkeypatch.setattr(lcd, "xgoscreen", package)
    monkeypatch.setattr(lcd, "pkgutil", SimpleNamespace(walk_packages=lambda *args: [(None, nested.__name__, False)]))

    def import_module(name):
        if name == nested.__name__:
            return nested
        raise ImportError(name)

    monkeypatch.setattr(lcd, "importlib", SimpleNamespace(import_module=import_module))
    original = sys.modules["drivers.lcd.ili9xx_device"]._iter_xgo_modules
    assert original() == [package, nested]


def test_lcd_cleanup_observes_replaced_facade_raw_state(lcd):
    calls = []

    def failed_close():
        calls.append("device")
        raise OSError("close failed")

    renderer = object.__new__(lcd.LCDRenderer)
    renderer.device = SimpleNamespace(SPI=SimpleNamespace(close=failed_close))
    renderer._bl_pin = 88
    lcd._RAWSPI = {"spi": SimpleNamespace(close=lambda: calls.append("raw")), "inited": True}
    renderer.cleanup()
    assert calls == ["device", "raw"]
    assert lcd._RAWSPI == {"spi": None, "inited": False}
    assert lcd.test_gpio.calls[-1] == ("cleanup", (88,), {})


@pytest.mark.parametrize(
    "bgr,swap,expected", [(0, 0, b"\xf8\0"), (1, 0, b"\0\x1f"), (0, 1, b"\0\xf8"), (1, 1, b"\x1f\0")]
)
def test_lcd_raw_presentation_preserves_colour_and_chunk_boundaries(lcd, monkeypatch, bgr, swap, expected):
    _environment(monkeypatch, lcd, {"FACE_BGR": str(bgr), "FACE_BYTESWAP": str(swap), "FACE_SPI_CHUNK": "1"})
    calls = []

    class Image:
        size = (1, 1)

        def convert(self, mode):
            assert mode == "RGB"
            return self

        def tobytes(self):
            return b"\xff\0\0"

    def failed_presenter(img):
        calls.append("presenter")
        raise ValueError("use RAW")

    renderer = object.__new__(lcd.LCDRenderer)
    renderer.width = renderer.height = 1
    renderer._present = failed_presenter
    renderer._raw_node = object()
    renderer._setw = lambda *args: calls.append(("window", args))
    renderer._cmd = lambda value: calls.append(("command", value))
    renderer._data = lambda value: calls.append(("data", bytes(value)))
    assert renderer.ShowImage(Image()) is None
    assert calls == [
        "presenter",
        ("window", (0, 0, 0, 0)),
        ("command", 0x2C),
        ("data", expected[:1]),
        ("data", expected[1:]),
    ]


def test_lcd_frame_success_with_none_does_not_fall_through(lcd):
    calls = []

    def rejected(*args):
        calls.append("rejected")
        raise ValueError("next variant")

    raw = SimpleNamespace(push_rgb565_3=rejected, push_frame=lambda *args: calls.append(args))
    renderer = SimpleNamespace(raw=raw, ShowImage=lambda img: pytest.fail("unexpected PIL fallback"))
    assert lcd._lcd_push_frame(renderer, 2, 3, b"pixels") is None
    assert calls == ["rejected", (2, 3, b"pixels")]


def test_lcd_installed_raw_path_preserves_false_write_data_fallback(lcd):
    calls = []
    low = SimpleNamespace(
        write_cmd=lambda value: calls.append(("command", value)),
        write_data=lambda value: calls.append(("data", value)),
        spi=SimpleNamespace(write=lambda value: calls.append(("spi", value))),
        dc_high=lambda: calls.append("dc"),
    )
    assert lcd._raw_install_push_rgb565_3(SimpleNamespace(device=low))
    assert low.push_rgb565_3(2, 3, b"pixels") is None
    assert calls == [
        ("command", 0x2A),
        ("data", b"\0\0\0\x01"),
        "dc",
        ("spi", [0, 0, 0, 1]),
        ("command", 0x2B),
        ("data", b"\0\0\0\x02"),
        "dc",
        ("spi", [0, 0, 0, 2]),
        ("command", 0x2C),
        ("data", b"pixels"),
    ]


def test_lcd_installed_window_and_ramwr_keep_bound_primitives(lcd):
    calls = []
    low = SimpleNamespace(set_window=lambda *args: calls.append(args), ramwr=lambda data: calls.append(data))
    assert lcd._raw_install_push_rgb565_3(SimpleNamespace(raw=low))
    low.set_window = lambda *args: pytest.fail("replacement must not change captured device primitive")
    assert low.push_rgb565_3(2, 3, b"frame") is None
    assert calls == [(0, 0, 1, 2), b"frame"]


@pytest.mark.parametrize("written,expected", [(1, True), (0, False)])
def test_lcd_fd_only_command_writes_one_byte(lcd, monkeypatch, written, expected):
    calls = []
    monkeypatch.setattr(lcd, "_cmd", None)
    monkeypatch.setattr(lcd, "_DEF_DC", None)
    lcd._RAWSPI = {"spi": SimpleNamespace(fileno=lambda: 44)}
    monkeypatch.setattr(lcd, "_os", SimpleNamespace(write=lambda fd, data: calls.append((fd, bytes(data))) or written))
    assert lcd._send_command_byte(0x12C) is expected
    assert calls == [(44, b"\x2c")]


@pytest.mark.parametrize(
    "kind,expected_lengths", [("write", [10]), ("fdwrite", [4, 4, 2]), ("xfer2", [4, 4, 2]), ("writebytes", [10])]
)
def test_lcd_effective_data_writer_respects_final_chunk_policy(lcd, monkeypatch, kind, expected_lengths):
    calls = []
    monkeypatch.setattr(lcd, "_spi_best_writer", lambda spi: (kind, calls.append))
    monkeypatch.setattr(lcd, "_SPI_CHUNK", 4)
    lcd._RAWSPI = {"spi": object()}
    lcd._data(bytes(range(10)))
    assert [len(value) for value in calls] == expected_lengths
    expected_type = list if kind in {"xfer2", "writebytes"} else memoryview
    assert all(isinstance(value, expected_type) for value in calls)


def test_lcd_frame_override_resolves_current_facade_helpers(lcd, monkeypatch):
    calls = []
    monkeypatch.setattr(lcd, "_spi_setup", lambda: calls.append("setup"))
    monkeypatch.setattr(lcd, "_maybe_set_window", lambda w, h: calls.append((w, h)))
    monkeypatch.setattr(lcd, "_ramwr_safe", lambda data: calls.append(data))
    lcd._RAW_STATE = {"win": None}
    renderer = object.__new__(lcd.LCDRenderer)
    renderer.push_frame(2, 3, b"first")
    renderer.push_frame(2, 3, b"second")
    assert calls == ["setup", (2, 3), b"first", "setup", b"second"]


def _frame(direction, address, payload, at=None):
    row = {
        "event": "frame",
        "direction": direction,
        "address": address,
        "mode": 2 if direction == "tx" else 0x12,
        "payload_hex": payload.hex(),
    }
    if at is not None:
        row["time_ns"] = at
    return row


def test_offline_correlation_capacity_keeps_the_bounded_tail():
    rows = [_frame("tx", 1, b"\x01") for _ in range(1025)]
    original = copy.deepcopy(rows)
    report = analyze(iter(rows))
    assert report["transaction_outcomes"] == {"correlation_capacity_limit": 1, "capture_ended_before_response": 1024}
    assert report["transactions"][0]["request_index"] == 0
    assert report["transactions"][-1]["request_index"] == 1024
    assert rows == original


def test_offline_timeout_is_observed_before_a_late_capture_gap():
    report = analyze([_frame("tx", 1, b"\x01", 0), {"direction": "gap", "time_ns": 100_000_001}])
    assert report["transaction_outcomes"] == {"no_response_within_observation_window": 1}
    assert report["continuity_gaps"] == 1
    assert report["capture_loss_observed"] is False


def test_capture_batch_limit_and_session_filter_are_preserved():
    capture = object.__new__(Capture)
    capture.events = queue.Queue()
    capture.active, capture.session = (True, "current")
    accepted = []
    capture._line = accepted.append
    for index in range(130):
        capture.events.put({"session": "old" if index == 0 else "current", "index": index})
    capture._drain_capture_events()
    assert len(accepted) == 127
    assert capture.events.qsize() == 2
    capture.active = False
    capture._drain_capture_events()
    assert capture.events.empty()
    assert len(accepted) == 127


def test_pending_response_retains_split_header_and_accepts_budget_boundary():
    payload = b"\x07"
    size, mode, address = (9, 3, 10)
    checksum = 255 - (size + mode + address + sum(payload)) % 256
    frame = bytes([0x55, 0, size, mode, address]) + payload + bytes([checksum, 0, 0xAA])
    pending = bytearray(b"noise\x55")
    assert protocol._parse_pending_response(pending, address, 1, 0, 1, lambda: 1) is None
    assert pending == b"\x55"
    pending.extend(frame[1:])
    result = protocol._parse_pending_response(pending, address, 1, 0, 1, lambda: 1)
    assert result["payload"] == payload
    assert pending == b""
    with pytest.raises(TimeoutError, match="sensor_read_timeout"):
        protocol._validate_response_frame(frame, address, 1, 0, 1, lambda: 1.000001)


def test_led_auto_prefers_kernel_default_and_rejects_unknown_without_writing(tmp_path, monkeypatch):
    path = tmp_path / "act"
    default = path / "device/of_node/linux,default-trigger"
    default.parent.mkdir(parents=True)
    default.write_bytes(b"heartbeat\0")
    (path / "trigger").write_text("none [timer] heartbeat")
    (path / "brightness").write_text("0")
    (path / "max_brightness").write_text("1")
    monkeypatch.setenv("RIDER_LED_SYSFS", str(tmp_path))
    result = led.apply({"action": "auto", "default_trigger": "none"})
    assert result["ok"] is True
    assert (path / "trigger").read_text() == "heartbeat"
    default.write_bytes(b"unknown\0")
    with pytest.raises(ValueError, match="led_default_trigger_unavailable"):
        led.apply({"action": "auto", "default_trigger": "heartbeat"})
    assert (path / "trigger").read_text() == "heartbeat"
