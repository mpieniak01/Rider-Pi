import pytest
from apps.hw.sink_lcd import SinkLCD
from PIL import Image

import builtins
import io
import sys
import types
import re

def test_sinklcd_push_auto_fallback(monkeypatch, capsys):
    # Symuluj brak SPI (brak sprzętu)
    lcd = SinkLCD(width=32, height=32, rotate=0, spi_hz=1000000, spi_dev="/dev/null", method="rgb565")
    lcd._spi = None  # erzac: wymuś brak SPI
    img = Image.new("RGB", (32, 32), (123, 222, 111))
    # Monkeypatch globalnie PIL.Image.Image.show
    called = {}
    orig_show = img.__class__.show
    def fake_show(self):
        called['show'] = True
    monkeypatch.setattr(img.__class__, 'show', fake_show)
    used = lcd.push_auto(img)
    out = capsys.readouterr().out
    assert used == 'pil'
    assert called.get('show') or '[sink_lcd] Fallback: ShowImage(PIL)' in out

def test_sinklcd_push_auto_raw(monkeypatch):
    # Mockuj spidev, erzac SPI
    sys.modules['spidev'] = types.SimpleNamespace(SpiDev=lambda: types.SimpleNamespace(open=lambda bus,dev: None, writebytes=lambda data: setattr(sys.modules['spidev'], 'data', data), max_speed_hz=0))
    class DummySPI:
        def writebytes(self, data):
            self.data = data
    lcd = SinkLCD(width=8, height=8, rotate=0, spi_hz=1000000, spi_dev="/dev/null", method="rgb565")
    lcd._spi = DummySPI()
    img = Image.new("RGB", (8, 8), (10, 20, 30))
    used = lcd.push_auto(img)
    assert used == 'rgb565'
    assert hasattr(lcd._spi, 'data')
