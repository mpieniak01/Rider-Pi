import pathlib
import sys

from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


def fake_sink(raw_supported: bool):
    class FakeSink:
        def supports_raw(self):
            return raw_supported

        def push_rgb565(self, frame_bytes, w, h):
            return "raw"

        def push_pil(self, image):
            return "pil"

    return FakeSink()


def test_sink_lcd_path_raw(monkeypatch):
    sink = fake_sink(True)
    assert sink.supports_raw() is True
    assert sink.push_rgb565(b"\x00" * 10, 1, 5) == "raw"


def test_sink_lcd_path_pil(monkeypatch):
    sink = fake_sink(False)
    assert sink.supports_raw() is False
    img = Image.new("RGB", (1, 1))
    assert sink.push_pil(img) == "pil"
