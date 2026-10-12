"""Camera ownership, startup failure and no-draw checks use fake backends."""

from types import SimpleNamespace

import pytest

from apps.camera import utils
from apps.camera.lcd_preview import open_preview


def test_picamera_release_is_idempotent_even_when_stop_fails():
    calls = []

    def stop():
        calls.append("stop")
        raise RuntimeError("stop failed")

    owner = utils.CameraReader(
        SimpleNamespace(stop=stop, close=lambda: calls.append("close")), lambda: None, picamera=True
    )
    with pytest.raises(RuntimeError):
        owner.close()
    owner.close()
    assert calls == ["stop", "close"]


def test_v4l2_owner_release():
    calls = []
    reader = utils.CameraReader(SimpleNamespace(release=lambda: calls.append("release")), lambda: (True, "frame"))
    assert reader() == (True, "frame")
    reader.close()
    reader.close()
    assert calls == ["release"]


@pytest.mark.parametrize("disabled,no_draw", [(True, False), (False, True), (True, True)])
def test_disabled_preview_does_not_create_lcd(monkeypatch, disabled, no_draw):
    monkeypatch.setattr("apps.camera.lcd_preview.LcdSink", lambda: pytest.fail("LCD initialized"))
    assert open_preview(disabled=disabled, no_draw=no_draw) is None


def test_active_preview_uses_common_lcd_sink(monkeypatch):
    owner = object()
    monkeypatch.setattr("apps.camera.lcd_preview.LcdSink", lambda: owner)
    assert open_preview() is owner


def test_picamera_failed_release_does_not_open_fallback(monkeypatch):
    monkeypatch.setattr(
        utils, "_picamera_reader", lambda size: (_ for _ in ()).throw(utils.CameraReleaseError("release"))
    )
    monkeypatch.setattr(utils, "_v4l2_reader", lambda size: pytest.fail("second owner opened"))
    with pytest.raises(utils.CameraReleaseError):
        utils.open_camera()
