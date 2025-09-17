from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Tuple, Callable, Any
import os, inspect, importlib, pkgutil

# --- zależności opcjonalne ---
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
    lcd_spi_hz: Optional[int] = None
    lcd_bl_pin: int = 13


# --- skan xgoscreen: wybór klasy z RAW (preferowane) albo ShowImage ---
def _iter_xgo_modules():
    mods = []
    if xgoscreen is None:
        return mods
    mods.append(xgoscreen)
    try:
        if hasattr(xgoscreen, "__path__"):
            for _, name, _ in pkgutil.walk_packages(xgoscreen.__path__, xgoscreen.__name__ + "."):
                try:
                    m = importlib.import_module(name)
                    mods.append(m)
                except Exception:
                    pass
    except Exception:
        pass
    for extra in ("xgoscreen.lcdconfig", "xgoscreen.lcd", "xgoscreen.screen"):
        try:
            m = importlib.import_module(extra)
            if m not in mods:
                mods.append(m)
        except Exception:
            pass
    return mods


def _score_class(cls) -> Tuple[int,str]:
    n = cls.__name__.lower()
    raw = all(hasattr(cls, m) for m in ("SetWindows", "command", "spi_writebyte"))
    pres = any(callable(getattr(cls, m, None)) for m in ("ShowImage","show_image","display","put","present"))
    score = 0
    if raw: score += 6
    if pres: score += 2
    # nazwy preferowane
    if "2inch" in n: score += 3
    if "st77" in n or "st7789" in n: score += 2
    if "lcd" in n or "display" in n or "panel" in n: score += 1
    # kara za ogólne "RaspberryPi"
    if n == "raspberrypi": score -= 4
    return score, cls.__name__


def _pick_device_class():
    if xgoscreen is None:
        raise RuntimeError(f"xgoscreen niezaładowany: {_XGO_ERR}")
    cands = []
    for m in _iter_xgo_modules():
        for name, obj in vars(m).items():
            if inspect.isclass(obj) and obj.__module__ == m.__name__:
                cands.append(obj)
    if not cands:
        raise RuntimeError("Nie znalazłem żadnej klasy w xgoscreen.*")
    cands.sort(key=_score_class, reverse=True)
    return cands[0]


# --- pomocnicze: znajdź presenter i RAW na konkretnym obiekcie ---
def _find_presenter(dev) -> Tuple[Optional[Any], Optional[Callable]]:
    for name in ("ShowImage","show_image","display","put","present"):
        fn = getattr(dev, name, None)
        if callable(fn):
            return dev, fn
    return None, None


def _find_raw_iface(dev) -> Tuple[Optional[Any], Optional[Callable], Optional[Callable], Optional[Callable]]:
    nodes = [dev, getattr(dev,'lcd',None), getattr(dev,'disp',None), getattr(dev,'display',None)]
    for node in nodes:
        if node is None: 
            continue
        if all(hasattr(node, m) for m in ("SetWindows","command","spi_writebyte")):
            return node, node.command, node.spi_writebyte, node.SetWindows
    return None, None, None, None


class LCDRenderer:
    width: int = 240
    height: int = 320

    def __init__(self, cfg: Optional[FaceConfig]=None):
        if Image is None:
            raise RuntimeError(f"Pillow niezaładowany: {_PIL_ERR}")
        if xgoscreen is None:
            raise RuntimeError(f"xgoscreen niezaładowany: {_XGO_ERR}")

        self.cfg = cfg or FaceConfig()

        DevClass = _pick_device_class()
        try:
            self.device = DevClass()
        except Exception:
            self.device = DevClass()
        print(f"[face] lcd_class={DevClass.__name__}", end=" ")

        # SPI hz / mode
        spi = getattr(self.device, "SPI", None)
        hz = self.cfg.lcd_spi_hz or int(os.getenv("FACE_LCD_SPI_HZ","0") or 0)
        if spi is not None:
            try:
                if hz:
                    spi.max_speed_hz = hz
                mode = int(os.getenv("FACE_SPI_MODE","0") or 0)
                if hasattr(spi, "mode"):
                    spi.mode = mode
            except Exception:
                pass
        print(f"disp={getattr(self.device,'width',self.width)}x{getattr(self.device,'height',self.height)}")
        if spi is not None:
            print(f"[face] LCD: spi.hz={getattr(spi,'max_speed_hz',hz)}  spi.mode={getattr(spi,'mode','-')}")

        # Backlight (BCM13 HIGH)
        try:
            import RPi.GPIO as GPIO
            bl_pin = int(os.getenv("FACE_LCD_BL_PIN", str(self.cfg.lcd_bl_pin)))
            GPIO.setmode(GPIO.BCM); GPIO.setwarnings(False)
            GPIO.setup(bl_pin, GPIO.OUT); GPIO.output(bl_pin, 1)
        except Exception:
            pass

        # delikatny begin/init
        if self.cfg.lcd_do_init:
            for name in ("begin","Begin","Init","init"):
                fn = getattr(self.device, name, None)
                if callable(fn):
                    try: fn(); break
                    except Exception: pass

        # wymiary
        for obj in (self.device, getattr(self.device,"lcd",None), getattr(self.device,"disp",None), getattr(self.device,"display",None)):
            if obj is None: continue
            w,h = getattr(obj,"width",None), getattr(obj,"height",None)
            if isinstance(w,int) and isinstance(h,int) and w>0 and h>0:
                self.width, self.height = w,h
                break

        # znajdź ścieżki
        self._present_obj, self._present = _find_presenter(self.device)
        self._raw_node, self._cmd, self._data, self._setw = _find_raw_iface(self.device)
        print(f"[face] presenter={'+' if self._present else '-'}  raw={'+' if self._raw_node else '-'}")

        # jeśli wymuszony RAW, wyłącz presenter
        self._force_raw = bool(int(os.getenv('FACE_FORCE_RAW','0') or 0))
        if self._force_raw:
            self._present_obj, self._present = None, None

        # sanity: jeśli nie ma ani ShowImage ani RAW – nie ma sensu iść dalej
        if (self._present is None) and (self._raw_node is None):
            raise RuntimeError("Brak ShowImage() i brak pełnego RAW (command/spi_writebyte/SetWindows) w xgoscreen.*")

    # --- rysowanie ---
    def ShowImage(self, img: Image.Image):
        print('[face] path=RAW (forced)' if bool(int(os.getenv('FACE_FORCE_RAW','0') or 0)) else ('[face] path=PRESENTER' if self._present else '[face] path=RAW'))
        if img.size != (self.width, self.height):
            img = img.resize((self.width, self.height), Image.BILINEAR)

        force_raw = bool(int(os.getenv('FACE_FORCE_RAW','0') or 0))

        # 1) presenter
        if (not force_raw) and self._present:
            try:
                print("[face] path=PRESENTER")
                self._present(img)
                return
            except Exception as e:
                print(f"[face] presenter failed: {e} → fallback RAW")

        # 2) RAW
        if self._raw_node is None:
            raise RuntimeError("Brak RAW interfejsu (command/spi_writebyte/SetWindows).")
        print("[face] path=RAW (forced)" if force_raw else "[face] path=RAW")

        rgb = img.convert("RGB")
        px = rgb.tobytes()

        BGR = bool(int(os.getenv("FACE_BGR","0") or 0))
        BYTESWAP = bool(int(os.getenv("FACE_BYTESWAP","0") or 0))

        out = bytearray(self.width*self.height*2)
        di = 0
        # pakowanie do RGB565
        for i in range(0, len(px), 3):
            r,g,b = px[i], px[i+1], px[i+2]
            if BGR:
                r,b = b,r
            v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            hi = (v >> 8) & 0xFF
            lo = v & 0xFF
            if BYTESWAP:
                hi, lo = lo, hi
            out[di]   = hi
            out[di+1] = lo
            di += 2

        self._setw(0, 0, self.width-1, self.height-1)
        self._cmd(0x2C)
        chunk = int(os.getenv("FACE_SPI_CHUNK","4096") or 4096)
        for off in range(0, len(out), chunk):
            self._data(out[off:off+chunk])
