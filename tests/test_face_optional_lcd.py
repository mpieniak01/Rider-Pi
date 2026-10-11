"""LCD ownership and rotation using an injected driver; no hardware imports."""

from types import SimpleNamespace

import pytest
from PIL import Image

from apps.ui.face.lcd_sink import LcdSink, LcdUnavailable


def test_busy_or_unknown_lcd_never_initializes_driver():
    for state in [{"free": False, "holders": [{"pid": 777}]}, {"free": True, "error": "failed"}]:
        with pytest.raises(LcdUnavailable):
            LcdSink(probe=lambda state=state: state, factory=lambda: pytest.fail("hardware opened"))


def test_rotation_and_owned_close(monkeypatch):
    monkeypatch.setenv("FACE_LCD_ROTATE", "270")
    calls = []
    driver = SimpleNamespace(
        device=SimpleNamespace(width=240, height=320, SPI=SimpleNamespace(close=lambda: calls.append("close"))),
        ShowImage=lambda image: calls.append(image.copy()),
    )
    sink = LcdSink(
        probe=lambda: {"free": True, "holders": []}, factory=lambda: driver, power_off=lambda: calls.append("off")
    )
    face = Image.new("RGB", (240, 240), (0, 20, 40))
    face.putpixel((0, 0), (255, 0, 0))
    sink.present(face)
    assert calls[0].size == (240, 320)
    assert calls[0].getpixel((239, 40)) == (255, 0, 0)
    sink.close()
    sink.close()
    assert calls[1:] == ["close", "off"]


def test_ownership_change_yields_before_next_write():
    clock = [0]
    state = {"free": True, "holders": []}
    frames = []
    driver = SimpleNamespace(device=SimpleNamespace(width=240, height=320), ShowImage=frames.append)
    sink = LcdSink(probe=lambda: state, factory=lambda: driver, power_off=lambda: None, clock=lambda: clock[0])
    clock[0] = 2
    state.update(free=False, holders=[{"pid": 777}])
    with pytest.raises(LcdUnavailable):
        sink.present(Image.new("RGB", (240, 240)))
    assert not frames
    sink.close()


def test_invalid_orientation_does_not_open_driver(monkeypatch):
    monkeypatch.setenv("FACE_LCD_ROTATE", "45")
    with pytest.raises(LcdUnavailable):
        LcdSink(probe=lambda: {"free": True, "holders": []}, factory=lambda: pytest.fail("opened"))


def test_reports_submitted_frame_and_accepted_power_off():
    reports = []
    driver = SimpleNamespace(_bl_pin=0, device=SimpleNamespace(width=240, height=320), ShowImage=lambda image: None)
    sink = LcdSink(
        probe=lambda: {"free": True, "holders": []},
        factory=lambda: driver,
        power_off=lambda: {"ok": True, "on": False},
        report=lambda **fields: reports.append(fields),
    )
    sink.present(Image.new("RGB", (240, 240)))
    sink.close()
    assert reports[0]["power_known"] is True
    assert reports[0]["frame"]["physical_validity"] == "unverified"
    assert reports[1]["on"] is False


def test_vendor_shared_spi_reopens_only_after_free_ownership(monkeypatch):
    import os

    from apps.ui.face import lcd_sink

    monkeypatch.setattr(lcd_sink, "_CLOSED_SPI", None)
    state = {"free": True, "holders": []}
    calls = []
    spi = SimpleNamespace(open=lambda *address: calls.append(("open", address)), close=lambda: calls.append("close"))

    def factory():
        state.update(free=False, holders=[{"pid": os.getpid(), "path": "/dev/spidev0.0"}])
        return SimpleNamespace(device=SimpleNamespace(SPI=spi), ShowImage=lambda image: None)

    first = LcdSink(probe=lambda: state, factory=factory, power_off=lambda: None)
    first.close()
    state.update(free=False, holders=[{"pid": 999, "path": "/dev/spidev0.0"}])
    with pytest.raises(LcdUnavailable):
        LcdSink(probe=lambda: state, factory=factory, power_off=lambda: None)
    assert calls == ["close"]
    state.update(free=True, holders=[])
    second = LcdSink(probe=lambda: state, factory=factory, power_off=lambda: None)
    assert calls == ["close", ("open", (0, 0))]
    second.close()
