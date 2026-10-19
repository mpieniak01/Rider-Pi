"""Public LCD compatibility after PR review; inert backend fixture only."""

from types import SimpleNamespace
from unittest.mock import Mock

from test_sonar306_drivers import lcd


def test_lcd_showimage_compatibility_name_keeps_same_callable_and_result(lcd, monkeypatch):
    monkeypatch.setenv("FACE_FORCE_RAW", "0")
    renderer = object.__new__(lcd.LCDRenderer)
    renderer.width, renderer.height = 2, 3
    renderer._present = Mock(return_value=object())
    renderer._raw_node = None
    image = SimpleNamespace(size=(2, 3))
    assert lcd.LCDRenderer.ShowImage is lcd.LCDRenderer.show_image
    assert renderer.ShowImage(image) is None
    renderer._present.assert_called_once_with(image)
