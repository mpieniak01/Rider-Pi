from __future__ import annotations

import importlib as importlib
import inspect as inspect
import os as os
import pkgutil as pkgutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from drivers.lcd.board import LCDBoard

_XGO_ERR = None
_PIL_ERR = None
try:
    import xgoscreen
except Exception as e:
    xgoscreen = None
    _XGO_ERR = e
try:
    from PIL import Image
except Exception as e:
    Image = None
    _PIL_ERR = e


@dataclass
class FaceConfig:
    lcd_do_init: bool = True
    lcd_rotate: int = 0
    lcd_spi_hz: int | None = None
    lcd_bl_pin: int = LCDBoard.bl


def _iter_xgo_modules():
    api = _runtime_namespace()
    mods = []
    if api['xgoscreen'] is None:
        return mods
    mods.append(api['xgoscreen'])
    try:
        if hasattr(api['xgoscreen'], '__path__'):
            for _, name, _ in api['pkgutil'].walk_packages(api['xgoscreen'].__path__, api['xgoscreen'].__name__ + '.'):
                try:
                    m = api['importlib'].import_module(name)
                    mods.append(m)
                except Exception:
                    pass
    except Exception:
        pass
    for extra in ('xgoscreen.lcdconfig', 'xgoscreen.lcd', 'xgoscreen.screen'):
        try:
            m = api['importlib'].import_module(extra)
            if m not in mods:
                mods.append(m)
        except Exception:
            pass
    return mods


def _score_class(cls) -> tuple[int, str]:
    n = cls.__name__.lower()
    raw = all(hasattr(cls, m) for m in ('SetWindows', 'command', 'spi_writebyte'))
    pres = any(callable(getattr(cls, m, None)) for m in ('ShowImage', 'show_image', 'display', 'put', 'present'))
    score = 0
    if raw:
        score += 6
    if pres:
        score += 2
    if '2inch' in n:
        score += 3
    if 'st77' in n or 'st7789' in n:
        score += 2
    if 'lcd' in n or 'display' in n or 'panel' in n:
        score += 1
    if n == 'raspberrypi':
        score -= 4
    return (score, cls.__name__)


def _pick_device_class():
    api = _runtime_namespace()
    if api['xgoscreen'] is None:
        raise RuntimeError(f"xgoscreen niezaładowany: {api['_XGO_ERR']}")
    cands = []
    for m in api['_iter_xgo_modules']():
        _ = None
        for _, obj in vars(m).items():
            _ = getattr(obj, '__name__', str(obj))
            if api['inspect'].isclass(obj) and obj.__module__ == m.__name__:
                cands.append(obj)
    if not cands:
        raise RuntimeError('Nie znalazłem żadnej klasy w xgoscreen.*')
    cands.sort(key=api['_score_class'], reverse=True)
    return cands[0]


def _find_presenter(dev) -> tuple[Any | None, Callable | None]:
    for name in ('ShowImage', 'show_image', 'display', 'put', 'present'):
        fn = getattr(dev, name, None)
        if callable(fn):
            return (dev, fn)
    return (None, None)


def _find_raw_iface(dev) -> tuple[Any | None, Callable | None, Callable | None, Callable | None]:
    nodes = [dev, getattr(dev, 'lcd', None), getattr(dev, 'disp', None), getattr(dev, 'display', None)]
    for node in nodes:
        if node is None:
            continue
        if all(hasattr(node, m) for m in ('SetWindows', 'command', 'spi_writebyte')):
            return (node, node.command, node.spi_writebyte, node.SetWindows)
    return (None, None, None, None)


def _runtime_namespace():
    """Resolve public driver overrides when the device layer is called."""
    facade = sys.modules.get('drivers.lcd.driver_ili9xx')
    return vars(facade) if facade is not None else globals()


def _rgb888_to_rgb565(px, width, height, bgr, byteswap):
    out = bytearray(width * height * 2)
    di = 0
    for i in range(0, len(px), 3):
        r, g, b = (px[i], px[i + 1], px[i + 2])
        if bgr:
            r, b = (b, r)
        value = (r & 248) << 8 | (g & 252) << 3 | b >> 3
        hi, lo = (value >> 8 & 255, value & 255)
        if byteswap:
            hi, lo = (lo, hi)
        out[di], out[di + 1] = (hi, lo)
        di += 2
    return out


class LCDRenderer:
    width: int = 240
    height: int = 320

    def __init__(self, cfg: FaceConfig | None = None):
        api = _runtime_namespace()
        if api['Image'] is None:
            raise RuntimeError(f"Pillow niezaładowany: {api['_PIL_ERR']}")
        if api['xgoscreen'] is None:
            raise RuntimeError(f"xgoscreen niezaładowany: {api['_XGO_ERR']}")
        self.cfg = cfg or api['FaceConfig']()
        device_class = api['_pick_device_class']()
        try:
            self.device = device_class()
        except Exception:
            self.device = device_class()
        print(f'[face] lcd_class={device_class.__name__}', end=' ')
        self._configure_spi()
        self._enable_backlight()
        self._begin_device()
        self._read_dimensions()
        self._select_paths()

    def _configure_spi(self):
        api = _runtime_namespace()
        spi = getattr(self.device, 'SPI', None)
        hz = self.cfg.lcd_spi_hz or int(api['os'].getenv('FACE_LCD_SPI_HZ', '0') or 0)
        if spi is not None:
            try:
                if hz:
                    spi.max_speed_hz = hz
                mode = int(api['os'].getenv('FACE_SPI_MODE', '0') or 0)
                if hasattr(spi, 'mode'):
                    spi.mode = mode
            except Exception:
                pass
        print(f"disp={getattr(self.device, 'width', self.width)}x{getattr(self.device, 'height', self.height)}")
        if spi is not None:
            print(f"[face] LCD: spi.hz={getattr(spi, 'max_speed_hz', hz)}  spi.mode={getattr(spi, 'mode', '-')}")

    def _enable_backlight(self):
        api = _runtime_namespace()
        self._bl_pin = None
        try:
            import RPi.GPIO as GPIO

            bl_pin = int(api['os'].getenv('FACE_LCD_BL_PIN', str(self.cfg.lcd_bl_pin)))
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(bl_pin, GPIO.OUT)
            GPIO.output(bl_pin, 1)
            self._bl_pin = bl_pin
        except Exception:
            pass

    def _begin_device(self):
        if not self.cfg.lcd_do_init:
            return
        for name in ('begin', 'Begin', 'Init', 'init'):
            fn = getattr(self.device, name, None)
            if callable(fn):
                try:
                    fn()
                    break
                except Exception:
                    pass

    def _read_dimensions(self):
        for obj in (
            self.device,
            getattr(self.device, 'lcd', None),
            getattr(self.device, 'disp', None),
            getattr(self.device, 'display', None),
        ):
            if obj is None:
                continue
            width, height = (getattr(obj, 'width', None), getattr(obj, 'height', None))
            if isinstance(width, int) and isinstance(height, int) and (width > 0) and (height > 0):
                self.width, self.height = (width, height)
                break

    def _select_paths(self):
        api = _runtime_namespace()
        self._present_obj, self._present = api['_find_presenter'](self.device)
        self._raw_node, self._cmd, self._data, self._setw = api['_find_raw_iface'](self.device)
        print(f"[face] presenter={('+' if self._present else '-')}  raw={('+' if self._raw_node else '-')}")
        self._force_raw = bool(int(api['os'].getenv('FACE_FORCE_RAW', '0') or 0))
        if self._force_raw:
            self._present_obj, self._present = (None, None)
        if self._present is None and self._raw_node is None:
            raise RuntimeError('Brak ShowImage() i brak pełnego RAW (command/spi_writebyte/SetWindows) w xgoscreen.*')

    def cleanup(self):
        """Graceful cleanup of LCD resources (SPI, GPIO).

        Note: This should only be called when the entire application is shutting down,
        as GPIO.cleanup() will affect all GPIO pins used by the application.
        """
        api = _runtime_namespace()
        try:
            spi = getattr(self.device, 'SPI', None)
            if spi is not None and hasattr(spi, 'close'):
                spi.close()
        except Exception:
            pass
        try:
            import RPi.GPIO as GPIO

            if self._bl_pin is not None:
                GPIO.output(self._bl_pin, 0)
                GPIO.cleanup(self._bl_pin)
        except Exception:
            pass
        try:
            if api['_RAWSPI'].get('spi'):
                raw_spi = api['_RAWSPI']['spi']
                if hasattr(raw_spi, 'close'):
                    raw_spi.close()
                api['_RAWSPI']['spi'] = None
                api['_RAWSPI']['inited'] = False
        except Exception:
            pass

    def _try_present_image(self, img, force_raw):
        if force_raw or not self._present:
            return False
        try:
            print('[face] path=PRESENTER')
            self._present(img)
            return True
        except Exception as error:
            print(f'[face] presenter failed: {error} → fallback RAW')
            return False

    def show_image(self, img: Image.Image):
        api = _runtime_namespace()
        path = '[face] path=RAW'
        if bool(int(api['os'].getenv('FACE_FORCE_RAW', '0') or 0)):
            path = '[face] path=RAW (forced)'
        elif self._present:
            path = '[face] path=PRESENTER'
        print(path)
        if img.size != (self.width, self.height):
            img = img.resize((self.width, self.height), api['Image'].BILINEAR)
        force_raw = bool(int(api['os'].getenv('FACE_FORCE_RAW', '0') or 0))
        if self._try_present_image(img, force_raw):
            return
        if self._raw_node is None:
            raise RuntimeError('Brak RAW interfejsu (command/spi_writebyte/SetWindows).')
        print('[face] path=RAW (forced)' if force_raw else '[face] path=RAW')
        px = img.convert('RGB').tobytes()
        bgr = bool(int(api['os'].getenv('FACE_BGR', '0') or 0))
        byteswap = bool(int(api['os'].getenv('FACE_BYTESWAP', '0') or 0))
        out = api['_rgb888_to_rgb565'](px, self.width, self.height, bgr, byteswap)
        self._setw(0, 0, self.width - 1, self.height - 1)
        self._cmd(44)
        chunk = int(api['os'].getenv('FACE_SPI_CHUNK', '4096') or 4096)
        for off in range(0, len(out), chunk):
            self._data(out[off : off + chunk])

    # Public compatibility name used by xgoscreen integrations.
    ShowImage = show_image
