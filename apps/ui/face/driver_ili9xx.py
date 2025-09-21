from __future__ import annotations

import builtins as _bi
import importlib
import inspect
import os
import os as _os
import pkgutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from time import time as _time
from typing import Any

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
    lcd_spi_hz: int | None = None
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


def _score_class(cls) -> tuple[int, str]:
    n = cls.__name__.lower()
    raw = all(hasattr(cls, m) for m in ("SetWindows", "command", "spi_writebyte"))
    pres = any(callable(getattr(cls, m, None)) for m in ("ShowImage", "show_image", "display", "put", "present"))
    score = 0
    if raw:
        score += 6
    if pres:
        score += 2
    # nazwy preferowane
    if "2inch" in n:
        score += 3
    if "st77" in n or "st7789" in n:
        score += 2
    if "lcd" in n or "display" in n or "panel" in n:
        score += 1
    # kara za ogólne "RaspberryPi"
    if n == "raspberrypi":
        score -= 4
    return score, cls.__name__


def _pick_device_class():
    if xgoscreen is None:
        raise RuntimeError(f"xgoscreen niezaładowany: {_XGO_ERR}")
    cands = []
    for m in _iter_xgo_modules():
        _ = None
        for _, obj in vars(m).items():
            _ = getattr(obj, "__name__", str(obj))
            if inspect.isclass(obj) and obj.__module__ == m.__name__:
                cands.append(obj)
    if not cands:
        raise RuntimeError("Nie znalazłem żadnej klasy w xgoscreen.*")
    cands.sort(key=_score_class, reverse=True)
    return cands[0]


# --- pomocnicze: znajdź presenter i RAW na konkretnym obiekcie ---
def _find_presenter(dev) -> tuple[Any | None, Callable | None]:
    for name in ("ShowImage", "show_image", "display", "put", "present"):
        fn = getattr(dev, name, None)
        if callable(fn):
            return dev, fn
    return None, None


def _find_raw_iface(dev) -> tuple[Any | None, Callable | None, Callable | None, Callable | None]:
    nodes = [
        dev,
        getattr(dev, "lcd", None),
        getattr(dev, "disp", None),
        getattr(dev, "display", None),
    ]
    for node in nodes:
        if node is None:
            continue
        if all(hasattr(node, m) for m in ("SetWindows", "command", "spi_writebyte")):
            return node, node.command, node.spi_writebyte, node.SetWindows
    return None, None, None, None


class LCDRenderer:
    width: int = 240
    height: int = 320

    def __init__(self, cfg: FaceConfig | None = None):
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
        hz = self.cfg.lcd_spi_hz or int(os.getenv("FACE_LCD_SPI_HZ", "0") or 0)
        if spi is not None:
            try:
                if hz:
                    spi.max_speed_hz = hz
                mode = int(os.getenv("FACE_SPI_MODE", "0") or 0)
                if hasattr(spi, "mode"):
                    spi.mode = mode
            except Exception:
                pass
        print(f"disp={getattr(self.device, 'width', self.width)}x{getattr(self.device, 'height', self.height)}")
        if spi is not None:
            print(f"[face] LCD: spi.hz={getattr(spi, 'max_speed_hz', hz)}  spi.mode={getattr(spi, 'mode', '-')}")

        # Backlight (BCM13 HIGH)
        try:
            import RPi.GPIO as GPIO

            bl_pin = int(os.getenv("FACE_LCD_BL_PIN", str(self.cfg.lcd_bl_pin)))
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(bl_pin, GPIO.OUT)
            GPIO.output(bl_pin, 1)
        except Exception:
            pass

        # delikatny begin/init
        if self.cfg.lcd_do_init:
            for name in ("begin", "Begin", "Init", "init"):
                fn = getattr(self.device, name, None)
                if callable(fn):
                    try:
                        fn()
                        break
                    except Exception:
                        pass

        # wymiary
        for obj in (
            self.device,
            getattr(self.device, "lcd", None),
            getattr(self.device, "disp", None),
            getattr(self.device, "display", None),
        ):
            if obj is None:
                continue
            w, h = getattr(obj, "width", None), getattr(obj, "height", None)
            if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
                self.width, self.height = w, h
                break

        # znajdź ścieżki
        self._present_obj, self._present = _find_presenter(self.device)
        self._raw_node, self._cmd, self._data, self._setw = _find_raw_iface(self.device)
        print(f"[face] presenter={'+' if self._present else '-'}  raw={'+' if self._raw_node else '-'}")

        # jeśli wymuszony RAW, wyłącz presenter
        self._force_raw = bool(int(os.getenv("FACE_FORCE_RAW", "0") or 0))
        if self._force_raw:
            self._present_obj, self._present = None, None

        # sanity: jeśli nie ma ani ShowImage ani RAW – nie ma sensu iść dalej
        if (self._present is None) and (self._raw_node is None):
            raise RuntimeError("Brak ShowImage() i brak pełnego RAW (command/spi_writebyte/SetWindows) w xgoscreen.*")

    # --- rysowanie ---
    def ShowImage(self, img: Image.Image):
        print(
            "[face] path=RAW (forced)"
            if bool(int(os.getenv("FACE_FORCE_RAW", "0") or 0))
            else ("[face] path=PRESENTER" if self._present else "[face] path=RAW")
        )
        if img.size != (self.width, self.height):
            img = img.resize((self.width, self.height), Image.BILINEAR)

        force_raw = bool(int(os.getenv("FACE_FORCE_RAW", "0") or 0))

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

        BGR = bool(int(os.getenv("FACE_BGR", "0") or 0))
        BYTESWAP = bool(int(os.getenv("FACE_BYTESWAP", "0") or 0))

        out = bytearray(self.width * self.height * 2)
        di = 0
        # pakowanie do RGB565
        for i in range(0, len(px), 3):
            r, g, b = px[i], px[i + 1], px[i + 2]
            if BGR:
                r, b = b, r
            v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            hi = (v >> 8) & 0xFF
            lo = v & 0xFF
            if BYTESWAP:
                hi, lo = lo, hi
            out[di] = hi
            out[di + 1] = lo
            di += 2

        self._setw(0, 0, self.width - 1, self.height - 1)
        self._cmd(0x2C)
        chunk = int(os.getenv("FACE_SPI_CHUNK", "4096") or 4096)
        for off in range(0, len(out), chunk):
            self._data(out[off : off + chunk])


# ---- Rider-Pi patch: RAW fastpath + path-log throttle ------------------------
# Ten blok dopina brakujące API i ogranicza spam logów bez ingerencji w istniejące metody.


try:
    from PIL import Image as _Image
except Exception:
    _Image = None


def _rgb565_to_pil(_w: int, _h: int, _buf: bytes):
    """Powolny fallback: konwersja RGB565 -> PIL.Image (tylko awaryjnie)."""
    if _Image is None:
        raise RuntimeError("PIL not available for fallback")
    # Konwersja ręczna (unikamy zależności od trybów 'RGB;16')
    import array

    raw = array.array("H", _buf)  # big-endian nieistotne po bitopsach
    out = bytearray(_w * _h * 3)
    j = 0
    for v in raw:
        r = (v >> 11) & 0x1F
        g = (v >> 5) & 0x3F
        b = v & 0x1F
        out[j + 0] = (r * 255) // 31
        out[j + 1] = (g * 255) // 63
        out[j + 2] = (b * 255) // 31
        j += 3
    return _Image.frombytes("RGB", (_w, _h), bytes(out))


def _lcd_push_frame(self, w: int, h: int, buf: bytes):
    """
    Publiczne API: szybki RAW push (RGB565, big-endian) — preferuje 'raw' ścieżkę.
    Variants, które próbujemy na pod-obiektach:
      push_rgb565_3(w,h,buf), push_rgb565(buf), blit_rgb565(w,h,buf), write_rgb565(w,h,buf)
    Fallback: konwersja do PIL + ShowImage (wolniejsza).
    """
    # 1) priorytet: obiekt 'raw' jeśli istnieje
    for target_name in ("raw", "device", "lcd", "renderer", "panel", "disp", "display"):
        tgt = getattr(self, target_name, None)
        if tgt is None:
            continue
        for name, sig in (
            ("push_rgb565_3", ("whb",)),
            ("push_frame", ("whb",)),
            ("blit_rgb565", ("whb",)),
            ("write_rgb565", ("whb",)),
            ("push_rgb565", ("b",)),
            ("draw565", ("whb",)),
        ):
            fn = getattr(tgt, name, None)
            if not callable(fn):
                continue
            try:
                if sig == ("whb",):
                    return fn(w, h, buf)
                elif sig == ("b",):
                    return fn(buf)
            except Exception as _e:
                # spróbuj kolejnego wariantu
                pass

    # 2) fallback: jeśli mamy dedykowane API w tej klasie
    for name in ("ShowRGB565",):
        fn = getattr(self, name, None)
        if callable(fn):
            try:
                return fn(w, h, buf)
            except Exception:
                pass

    # 3) ostateczny fallback: konwersja do PIL i użycie ShowImage
    img = _rgb565_to_pil(w, h, buf)
    show = getattr(self, "ShowImage", None)
    if not callable(show):
        raise RuntimeError("No raw path and no ShowImage available")
    return show(img)


# Podłącz metodę do klasy (jeśli nie istnieje)
try:
    _ = LCDRenderer
    if not hasattr(LCDRenderer, "push_frame"):
        LCDRenderer.push_frame = _lcd_push_frame
except NameError:
    pass


# Log throttle: jeśli implementacja loguje `path=...` każdą klatkę, ogranicz do co 5 s
def _wrap_path_logger(obj):
    # Szukamy atrybutu/eventu logującego, tu zakładamy metodę `log_path(path)`
    log_fn = getattr(obj, "log_path", None)
    if not callable(log_fn):
        # alternatywnie: jeśli używane jest print(), nie owiniemy — zostawiamy jak jest
        return
    _last = {"ts": 0, "path": None}

    def _throttled(path):
        now = _time()
        if path != _last["path"] or (now - _last["ts"]) >= 5.0:
            _last["path"] = path
            _last["ts"] = now
            return log_fn(path)

    obj.log_path = _throttled


# Spróbuj owinąć self (instancję) na końcu inicjalizacji sterownika
try:
    _orig_begin = LCDRenderer.begin  # type: ignore[attr-defined]

    def _begin_with_throttle(self, *a, **kw):
        try:
            _wrap_path_logger(self)
        except Exception:
            pass
        return _orig_begin(self, *a, **kw)

    LCDRenderer.begin = _begin_with_throttle  # type: ignore[assignment]
except Exception:
    # jeśli nie ma begin(), to trudno — patch nie jest krytyczny
    pass
# ------------------------------------------------------------------------------
# ---- Rider-Pi: true RAW fastpath for RGB565 over SPI -------------------------
# Szukamy najniższej warstwy (raw/device/lcd/...) i dopinamy metodę push_rgb565_3
# wykorzystując istniejące prymitywy: set_window/CASET/RASET + RAMWR + write bytes.


def _find_ll(dev, names):
    for n in names:
        o = getattr(dev, n, None)
        if o is not None:
            return o
    return None


def _pick(dev, candidates):
    for n in candidates:
        fn = getattr(dev, n, None)
        if callable(fn):
            return fn
    return None


def _raw_install_push_rgb565_3(root):
    low = _find_ll(root, ("raw", "device", "lcd", "panel", "disp", "display"))
    if low is None:
        return False

    # spróbuj istniejących metod surowych:
    if _pick(low, ("push_rgb565_3", "blit_rgb565", "write_rgb565", "push_frame")):
        return True  # już jest

    # prymitywy okienka/komend/danych
    set_window = _pick(low, ("set_window", "setaddrwindow", "window"))
    write_cmd = _pick(low, ("write_cmd", "cmd", "command", "writecommand"))
    write_data = _pick(low, ("write_data", "data", "writedata"))
    ramwr = _pick(low, ("ram_write", "ramwr", "memory_write"))

    # dostęp do SPI bezpośrednio (jeśli nie masz write_data)
    spi = getattr(low, "spi", None)
    spi_write = None
    if spi is not None:
        spi_write = _pick(spi, ("write", "writebytes", "xfer2"))

    # DC pin toggle (opcjonalnie, jeśli brak write_cmd/write_data)
    dc_high = _pick(low, ("dc_high", "dc_on", "datamode"))
    dc_low = _pick(low, ("dc_low", "dc_off", "commandmode"))

    # jeśli nie mamy żadnego sposobu na wysłanie danych — poddajemy się
    if not (set_window or (write_cmd and (write_data or spi_write))):
        return False

    # implementacja: set_window + RAMWR + write bytes
    def _push_rgb565_3(w: int, h: int, buf: bytes):
        # okno pełnoekranowe (zakładamy, że obraz już jest w orientacji panelu)
        if set_window:
            set_window(0, 0, w - 1, h - 1)
        else:
            # CASET/RASET ręcznie
            if write_cmd:
                write_cmd(0x2A)
                (write_data and write_data(bytes([0, 0, 0, w - 1]))) or (
                    dc_high and dc_high() or None,
                    spi_write and spi_write([0, 0, 0, w - 1]),
                )
                write_cmd(0x2B)
                (write_data and write_data(bytes([0, 0, 0, h - 1]))) or (
                    dc_high and dc_high() or None,
                    spi_write and spi_write([0, 0, 0, h - 1]),
                )
        # RAMWR
        if ramwr:
            ramwr(buf)
            return
        if write_cmd:
            write_cmd(0x2C)  # RAMWR
        else:
            # bezpośredni tryb command, jeśli dostępny
            if dc_low:
                dc_low()
            if spi_write:
                spi_write([0x2C])
        # data
        if write_data:
            write_data(buf)
        elif spi_write:
            if dc_high:
                dc_high()
            # spidev.xfer2 chce list[int], write/writebytes przyjmą bytes
            spi_write(list(buf) if spi_write.__name__ == "xfer2" else buf)
        else:
            raise RuntimeError("No data path for raw push")

    # podłącz
    low.push_rgb565_3 = _push_rgb565_3
    return True


# na starcie spróbuj zainstalować RAW fastpath i przełączyć push_frame na niego
try:
    if _raw_install_push_rgb565_3(LCDRenderer):  # type: ignore[name-defined]

        def _push_frame_pref_raw(self, w: int, h: int, buf: bytes):
            # preferuj surową metodę z dolnej warstwy
            low = _find_ll(self, ("raw", "device", "lcd", "panel", "disp", "display"))
            fn = _pick(low, ("push_rgb565_3", "blit_rgb565", "write_rgb565", "push_frame"))
            if fn:
                return fn(w, h, buf)
            # fallback do starego zachowania (PIL)
            return _lcd_push_frame(self, w, h, buf)  # z wcześniejszego patcha

        LCDRenderer.push_frame = _push_frame_pref_raw  # type: ignore[attr-defined]
except Exception:
    pass
# -----------------------------------------------------------------------------------
# ==== Rider-Pi: TRUE RAW SPI FASTPATH (RGB565, big-endian) =====================
# Ten blok dodaje metodę push_rgb565_3(w,h,buf) na dolnej warstwie SPI i
# przekierowuje LCDRenderer.push_frame tak, aby używał jej ZAMIAST fallbacku PIL.


try:
    import spidev as _spidev
except Exception:
    _spidev = None
try:
    import RPi.GPIO as _GPIO
except Exception:
    _GPIO = None

_DEF_SPI = os.getenv("FACE_LCD_SPI_DEV", "/dev/spidev0.0")
_DEF_HZ = int(os.getenv("FACE_LCD_SPI_HZ", "48000000") or 0) or 32000000
_DEF_MODE = int(os.getenv("FACE_SPI_MODE", "0") or 0)
_DEF_DC = int(os.getenv("FACE_LCD_DC_PIN", "25") or 25)
_DEF_RST = int(os.getenv("FACE_LCD_RST_PIN", "27") or 27)

_RAWSPI = {"spi": None, "inited": False}


def _spi_setup():
    if _RAWSPI["inited"]:
        return
    if _spidev is None or _GPIO is None:
        raise RuntimeError("RAW fastpath needs python3-spidev + python3-rpi.gpio")
    # parse dev
    bus, dev = 0, 0
    if _DEF_SPI.startswith("/dev/spidev"):
        try:
            bus, dev = map(int, _DEF_SPI.replace("/dev/spidev", "").split("."))
        except Exception:
            pass
    # GPIO
    _GPIO.setwarnings(False)
    _GPIO.setmode(_GPIO.BCM)
    _GPIO.setup(_DEF_DC, _GPIO.OUT, initial=_GPIO.LOW)
    _GPIO.setup(_DEF_RST, _GPIO.OUT, initial=_GPIO.HIGH)

    # hard reset
    _GPIO.output(_DEF_RST, _GPIO.HIGH)
    time.sleep(0.01)
    _GPIO.output(_DEF_RST, _GPIO.LOW)
    time.sleep(0.02)
    _GPIO.output(_DEF_RST, _GPIO.HIGH)
    time.sleep(0.12)

    # SPI
    spi = _spidev.SpiDev()
    spi.open(bus, dev)
    spi.max_speed_hz = _DEF_HZ
    spi.mode = _DEF_MODE
    _RAWSPI["spi"] = spi

    # minimal wake sequence (bez pełnej init-sekwencji — panel już skonfigurowany w systemie)
    _cmd(0x11)  # SLP_OUT
    time.sleep(0.12)
    _cmd(0x29)  # DISP_ON

    _RAWSPI["inited"] = True


def _cmd(c: int):
    # DC=0 (command), wyślij 1 bajt
    _GPIO.output(_DEF_DC, _GPIO.LOW)
    spi = _RAWSPI["spi"]
    if hasattr(spi, "writebytes"):
        spi.writebytes([c & 0xFF])
    else:
        spi.xfer2([c & 0xFF])


def _data(bs: bytes):
    _dc_high_guarded()
    spi = _RAWSPI["spi"]
    kind, send = _spi_best_writer(spi)
    if not _RAW_DBG_ONCE["done"]:
        print(f"[raw] path={kind or 'NONE'}", flush=True)
        _RAW_DBG_ONCE["done"] = True
    mv = memoryview(bs)
    if kind in ("write", "writebytes2"):
        send(mv)  # jeden strzał, bez list()
    elif kind == "fdwrite":
        # niektóre kernele ograniczają rozmiar write() -> chunk
        n = len(mv)
        i = 0
        while i < n:
            j = i + _SPI_CHUNK
            send(mv[i:j])
            i = j
    elif kind in ("xfer3", "xfer2"):
        # xfer* wymaga list[int]; chunk + konwersja
        step = min(_SPI_CHUNK, 4096)
        n = len(mv)
        i = 0
        while i < n:
            j = i + step
            send(list(mv[i:j]))
            i = j
    else:
        send(list(mv))  # ostatni fallback         # jeden xfer/list — nadal 1 strzał


# ============================================================================
# ==== Rider-Pi: cache CASET/RASET (window) to avoid per-frame overhead =========
try:
    _ = _RAW_STATE
except NameError:
    _RAW_STATE = {"win": None}


def _raw_push_rgb565_3(w: int, h: int, buf: bytes):
    # szybka ścieżka: ustaw okno tylko jeśli się zmieniło
    _spi_setup()
    win = _RAW_STATE.get("win")
    if win != (w, h):
        _caset(0, w - 1)  # noqa: F821
        _raset(0, h - 1)  # noqa: F821
        _RAW_STATE["win"] = (w, h)
    _ramwr(buf)  # RAMWR + data (jednym strzałem w _data)  # noqa: F821


# re-attach in case earlier defined version exists
try:
    _ = LCDRenderer
    low = getattr(LCDRenderer, "raw", None) or LCDRenderer
    low.push_rgb565_3 = _raw_push_rgb565_3
except Exception:
    pass
# ===============================================================================
# ==== Rider-Pi: local print-filter to cut noisy '[face] path=...' ==============

if not hasattr(_bi, "_rider_print_orig"):
    _bi._rider_print_orig = _bi.print

    def _rider_print(*a, **kw):
        try:
            s = a[0] if a else ""
            if isinstance(s, str) and s.startswith("[face] path="):
                return  # drop
        except Exception:
            pass
        return _bi._rider_print_orig(*a, **kw)

    _bi.print = _rider_print
# ===============================================================================
# ==== Rider-Pi: forceable SPI send path + explicit debug =======================

_FORCE_SEND = (
    _os.getenv("FACE_SPI_SEND", "").strip().lower()
)  # "", "fdwrite","write","writebytes2","xfer2","writebytes"


def _spi_best_writer(spi):
    # Jeśli wymuszono konkretną metodę — honoruj
    if _FORCE_SEND:
        if _FORCE_SEND == "fdwrite":
            try:
                fd = spi.fileno()
                if isinstance(fd, int) and fd > 0:
                    return ("fdwrite", lambda b: _os.write(fd, b))
            except Exception:
                pass
        fn = getattr(spi, _FORCE_SEND, None)
        if callable(fn):
            return (_FORCE_SEND, fn)
        # jeśli wymuszenie się nie udało, lecimy normalnym rankingiem

    # Ranking automatyczny (bez konwersji do list na pierwszym miejscu)
    try:
        fd = spi.fileno()
        if isinstance(fd, int) and fd > 0:
            return ("fdwrite", lambda b: _os.write(fd, b))
    except Exception:
        pass
    if hasattr(spi, "write"):
        return ("write", spi.write)
    if hasattr(spi, "writebytes2"):
        return ("writebytes2", spi.writebytes2)
    if hasattr(spi, "xfer3"):
        return ("xfer3", spi.xfer3)
    if hasattr(spi, "xfer2"):
        return ("xfer2", spi.xfer2)
    if hasattr(spi, "writebytes"):
        return ("writebytes", spi.writebytes)
    return (None, None)


# pokaż raz, którą ścieżkę wybrano
try:
    _ = _RAW_DBG_SHOWN
except NameError:
    _RAW_DBG_SHOWN = {"done": False}


def _data(bs: bytes):
    """DC=1, preferuj one-shot bez konwersji; fallback: pojedynczy xfer(list)."""
    _GPIO.output(_DEF_DC, _GPIO.HIGH)
    spi = _RAWSPI["spi"]
    kind, send = _spi_best_writer(spi)
    if not _RAW_DBG_SHOWN["done"]:
        print(f"[raw] spi send path = {kind or 'NONE'} (forced={_FORCE_SEND or '-'})", flush=True)
        _RAW_DBG_SHOWN["done"] = True
    if send is None:
        raise RuntimeError("SPI has no usable write method")
    mv = memoryview(bs)
    if kind in ("fdwrite", "write", "writebytes2"):
        send(mv)  # 1 strzał, bez list
    else:
        send(list(mv))  # 1 strzał, ale z konwersją do listy (wolniej)


# ==============================================================================
# ==== DIAG: pokaż realny max_speed_hz i ścieżkę wysyłki raz ===================
try:
    _ = _SPI_DBG_ONCE
except NameError:
    _SPI_DBG_ONCE = {"done": False}


def _spi_setup():
    global _RAWSPI
    if _RAWSPI.get("spi"):
        return
    import spidev as _spidev

    spi = _spidev.SpiDev()
    bus, dev = _DEF_SPI_DEV  # noqa: F821
    spi.open(bus, dev)
    spi.max_speed_hz = _DEF_HZ
    spi.mode = _DEF_MODE
    spi.bits_per_word = 8
    for attr, val in (
        ("lsbfirst", False),
        ("cshigh", False),
        ("threewire", False),
        ("loop", False),
    ):
        try:
            setattr(spi, attr, val)
        except Exception:
            pass
    _RAWSPI["spi"] = spi
    if not _SPI_DBG_ONCE["done"]:
        try:
            print(
                f"[spi] requested_hz={_DEF_HZ} actual_hz={spi.max_speed_hz} mode={spi.mode} bpw={getattr(spi, 'bits_per_word', 8)}",
                flush=True,
            )
        except Exception:
            pass
        _SPI_DBG_ONCE["done"] = True


try:
    _ = _RAW_DBG_ONCE
except NameError:
    _RAW_DBG_ONCE = {"done": False}


def _spi_best_writer(spi):
    # preferuj fdwrite/write/writebytes2
    try:
        fd = spi.fileno()
        if isinstance(fd, int) and fd > 0:
            return ("fdwrite", lambda b: _os.write(fd, b))
    except Exception:
        pass
    if hasattr(spi, "write"):
        return ("write", spi.write)
    if hasattr(spi, "writebytes2"):
        return ("writebytes2", spi.writebytes2)
    if hasattr(spi, "xfer3"):
        return ("xfer3", spi.xfer3)
    if hasattr(spi, "xfer2"):
        return ("xfer2", spi.xfer2)
    if hasattr(spi, "writebytes"):
        return ("writebytes", spi.writebytes)
    return (None, None)


def _data(bs: bytes):
    _GPIO.output(_DEF_DC, _GPIO.HIGH)
    spi = _RAWSPI["spi"]
    kind, send = _spi_best_writer(spi)
    if not _RAW_DBG_ONCE["done"]:
        print(f"[raw] path={kind or 'NONE'}", flush=True)
        _RAW_DBG_ONCE["done"] = True
    mv = memoryview(bs)
    if kind in ("fdwrite", "write", "writebytes2"):
        send(mv)  # jeden write, bez list()
    else:
        send(list(mv))  # fallback (wolniej)


# ==============================================================================
# ==== Rider-Pi RAW fastpath: force push_frame → RAMWR + _data (one-shot) ======
# Jednorazowe logi diagnostyczne:
try:
    _ = _SPI_DBG_ONCE
except NameError:
    _SPI_DBG_ONCE = {"done": False}
try:
    _ = _RAW_DBG_ONCE
except NameError:
    _RAW_DBG_ONCE = {"done": False}


def _spi_best_writer(spi):
    # preferuj metody bez konwersji list
    try:
        fd = spi.fileno()
        if isinstance(fd, int) and fd > 0:
            return ("fdwrite", lambda b: _os.write(fd, b))
    except Exception:
        pass
    if hasattr(spi, "write"):
        return ("write", spi.write)
    if hasattr(spi, "writebytes2"):
        return ("writebytes2", spi.writebytes2)
    if hasattr(spi, "xfer3"):
        return ("xfer3", spi.xfer3)
    if hasattr(spi, "xfer2"):
        return ("xfer2", spi.xfer2)
    if hasattr(spi, "writebytes"):
        return ("writebytes", spi.writebytes)
    return (None, None)


def _spi_setup():
    global _RAWSPI
    if _RAWSPI.get("spi"):
        return
    import spidev as _spidev

    spi = _spidev.SpiDev()
    bus, dev = _DEF_SPI_DEV  # noqa: F821
    spi.open(bus, dev)
    spi.max_speed_hz = _DEF_HZ
    spi.mode = _DEF_MODE
    spi.bits_per_word = 8
    for attr, val in (
        ("lsbfirst", False),
        ("cshigh", False),
        ("threewire", False),
        ("loop", False),
    ):
        try:
            setattr(spi, attr, val)
        except Exception:
            pass
    _RAWSPI["spi"] = spi
    if not _SPI_DBG_ONCE["done"]:
        try:
            print(
                f"[spi] requested_hz={_DEF_HZ} actual_hz={spi.max_speed_hz} mode={spi.mode} bpw={getattr(spi, 'bits_per_word', 8)}",
                flush=True,
            )
        except Exception:
            pass
        _SPI_DBG_ONCE["done"] = True


def _data(bs: bytes):
    _GPIO.output(_DEF_DC, _GPIO.HIGH)
    spi = _RAWSPI["spi"]
    kind, send = _spi_best_writer(spi)
    if not _RAW_DBG_ONCE["done"]:
        print(f"[raw] path={kind or 'NONE'}", flush=True)
        _RAW_DBG_ONCE["done"] = True
    mv = memoryview(bs)
    if kind in ("fdwrite", "write", "writebytes2"):
        send(mv)  # jeden write, bez list()
    else:
        send(list(mv))  # fallback (wolniej)


# cache okna (CASET/RASET tylko jeśli zmiana rozmiaru)
try:
    _ = _RAW_STATE
except NameError:
    _RAW_STATE = {"win": None}


def _force_push_frame(self, w: int, h: int, buf: bytes):
    _spi_setup()
    if _RAW_STATE["win"] != (w, h):
        _caset(0, w - 1)  # noqa: F821
        _raset(0, h - 1)  # noqa: F821
        _RAW_STATE["win"] = (w, h)
    _ramwr(buf)  # RAMWR + _data(bytes) → one-shot  # noqa: F821


# Twarde nadpisanie push_frame na klasie sterownika:
try:
    _ = LCDRenderer
    LCDRenderer.push_frame = _force_push_frame
    # jeśli jest sub-obiekt raw:
    low = getattr(LCDRenderer, "raw", None)
    if low is not None:
        low.push_frame = _force_push_frame
except Exception as e:
    print("[force] patch push_frame failed:", e)


# ==============================================================================
# ==== SAFE RAW FASTPATH (fallbacks for SPI defs + guarded DC) =================
# Fallback getters for module-level config (work across variants)
def _get_mod(name, default=None):
    return globals().get(name, default)


def _spi_params():
    # bus/dev
    busdev = _get_mod("_DEF_SPI_DEV") or _get_mod("DEF_SPI_DEV") or (0, 0)
    if not (isinstance(busdev, (tuple, list)) and len(busdev) == 2):
        busdev = (0, 0)
    bus, dev = int(busdev[0]), int(busdev[1])
    # speed/mode
    hz = _get_mod("_DEF_HZ") or _get_mod("DEF_HZ") or 32000000
    mode = _get_mod("_DEF_MODE") or _get_mod("DEF_MODE") or 0
    try:
        hz = int(hz)
    except Exception:
        hz = 32000000
    try:
        mode = int(mode)
    except Exception:
        mode = 0
    return bus, dev, hz, mode


# one-time debug toggles
try:
    _ = _SPI_DBG_ONCE
except NameError:
    _SPI_DBG_ONCE = {"done": False}
try:
    _ = _RAW_DBG_ONCE
except NameError:
    _RAW_DBG_ONCE = {"done": False}


def _spi_best_writer(spi):
    # prefer paths that accept bytes/memoryview
    try:
        fd = spi.fileno()
        if isinstance(fd, int) and fd > 0:
            return ("fdwrite", lambda b: _os.write(fd, b))
    except Exception:
        pass
    if hasattr(spi, "write"):
        return ("write", spi.write)
    if hasattr(spi, "writebytes2"):
        return ("writebytes2", spi.writebytes2)
    if hasattr(spi, "xfer3"):
        return ("xfer3", spi.xfer3)
    if hasattr(spi, "xfer2"):
        return ("xfer2", spi.xfer2)
    if hasattr(spi, "writebytes"):
        return ("writebytes", spi.writebytes)
    return (None, None)


def _spi_setup():
    global _RAWSPI
    if _RAWSPI.get("spi"):
        return
    import spidev as _spidev

    spi = _spidev.SpiDev()
    bus, dev, hz, mode = _spi_params()
    spi.open(bus, dev)
    spi.max_speed_hz = hz
    spi.mode = mode
    # keep it 8-bit
    try:
        spi.bits_per_word = 8
    except Exception:
        pass
    # conservative flags
    for attr, val in (
        ("lsbfirst", False),
        ("cshigh", False),
        ("threewire", False),
        ("loop", False),
    ):
        try:
            setattr(spi, attr, val)
        except Exception:
            pass
    _RAWSPI["spi"] = spi
    if not _SPI_DBG_ONCE["done"]:
        try:
            bpw = getattr(spi, "bits_per_word", 8)
            print(
                f"[spi] requested_hz={hz} actual_hz={spi.max_speed_hz} mode={spi.mode} bpw={bpw}",
                flush=True,
            )
        except Exception:
            pass
        _SPI_DBG_ONCE["done"] = True


def _dc_high_guarded():
    # Toggle DC only if both _GPIO and _DEF_DC exist
    if "_GPIO" in globals():
        dc = _get_mod("_DEF_DC")
        if dc is not None:
            try:
                _GPIO.output(dc, _GPIO.HIGH)
            except Exception:
                pass


def _data(bs: bytes):
    _dc_high_guarded()
    spi = _RAWSPI["spi"]
    kind, send = _spi_best_writer(spi)
    if not _RAW_DBG_ONCE["done"]:
        print(f"[raw] path={kind or 'NONE'}", flush=True)
        _RAW_DBG_ONCE["done"] = True
    mv = memoryview(bs)
    if kind in ("fdwrite", "write", "writebytes2"):
        send(mv)  # one-shot without list()
    else:
        send(list(mv))  # fallback (slower)


# cache window (set once per WxH)
try:
    _ = _RAW_STATE
except NameError:
    _RAW_STATE = {"win": None}


def _force_push_frame(self, w: int, h: int, buf: bytes):
    _spi_setup()
    if _RAW_STATE["win"] != (w, h):
        _caset(0, w - 1)  # noqa: F821
        _raset(0, h - 1)  # noqa: F821
        _RAW_STATE["win"] = (w, h)
    _ramwr(buf)  # RAMWR + data → uses our _data()  # noqa: F821


# attach override
try:
    _ = LCDRenderer
    LCDRenderer.push_frame = _force_push_frame
    low = getattr(LCDRenderer, "raw", None)
    if low is not None:
        low.push_frame = _force_push_frame
except Exception as e:
    print("[force] patch push_frame failed:", e)


# ==============================================================================
# ---- window setter (best-effort) ----------------------------------------------
def _maybe_set_window(w: int, h: int):
    # spróbuj różnych nazw/setterów okna
    for fname in ("_set_window", "set_window", "window", "SetWindow", "setwin", "win"):
        fn = globals().get(fname)
        if callable(fn):
            for args in ((0, 0, w - 1, h - 1), (0, w - 1, 0, h - 1), (0, w - 1, h - 1, 0)):
                try:
                    fn(*args)
                    return True
                except Exception:
                    pass
    # klasyczne CAS/RAS jeśli istnieją
    caset = globals().get("_caset")
    raset = globals().get("_raset")
    if callable(caset) and callable(raset):
        try:
            caset(0, w - 1)
            raset(0, h - 1)
            return True
        except Exception:
            pass
    return False


# ---- bezpieczne, wymuszone push_frame → RAMWR + _data (one-shot) --------------
def _force_push_frame(self, w: int, h: int, buf: bytes):
    _spi_setup()
    global _RAW_STATE
    try:
        _ = _RAW_STATE
    except NameError:
        _RAW_STATE = {"win": None}
    if _RAW_STATE.get("win") != (w, h):
        _maybe_set_window(w, h)
        _RAW_STATE["win"] = (w, h)
    _ramwr(buf)  # RAMWR + data → używa naszego _data()  # noqa: F821


# zbindowanie override (nawet jeśli już wcześniej łapaliśmy wyjątek)
try:
    _ = LCDRenderer
    LCDRenderer.push_frame = _force_push_frame
    low = getattr(LCDRenderer, "raw", None)
    if low is not None:
        low.push_frame = _force_push_frame
except Exception as e:
    print("[force] patch push_frame rebind failed:", e)


# ---- safe command sender + RAMWR fallback ------------------------------------
def _send_command_byte(cmd_val: int) -> bool:
    """Wyślij bajt komendy LCD. Najpierw próbujemy istniejące prymitywy (_cmd/command/...),
    a jeśli brak – robimy minimalny fallback na DC=LOW + SPI write jednego bajtu."""
    # 1) spróbuj gotowych funkcji z modułu
    for fname in ("_cmd", "cmd", "command", "write_cmd", "Write_Command", "send_cmd"):
        fn = globals().get(fname)
        if callable(fn):
            try:
                fn(cmd_val & 0xFF)
                return True
            except Exception:
                pass
    # 2) fallback: DC LOW + SPI write(1B)
    try:
        dc = _get_mod("_DEF_DC")
        if dc is not None and "_GPIO" in globals():
            _GPIO.output(dc, _GPIO.LOW)
        spi = _RAWSPI.get("spi")
        if spi is None:
            _spi_setup()
            spi = _RAWSPI.get("spi")
        kind, send = _spi_best_writer(spi)
        b = bytes((cmd_val & 0xFF,))
        mv = memoryview(b)
        if kind in ("write", "writebytes2"):
            send(mv)
        elif kind == "fdwrite":
            _send_chunked(lambda bb: _os.write(spi.fileno(), bb), mv, 1)  # noqa: F821
        elif kind in ("xfer3", "xfer2", "writebytes"):
            send(list(mv))
        else:
            return False
        return True
    except Exception:
        return False


def _ramwr_safe(payload: bytes):
    """Zamiennik _ramwr: wyślij 0x2C (RAMWR), potem dane przez _data()."""
    if not _send_command_byte(0x2C):
        # Jeśli nie udało się wysłać komendy – próbujemy mimo to dane (część kontrolerów
        # bywa „w trybie RAMWR” po wcześniejszych operacjach).
        pass
    _data(payload)


# ---- zaktualizuj wymuszone push_frame, by korzystało z _ramwr_safe -----------
def _force_push_frame(self, w: int, h: int, buf: bytes):
    _spi_setup()
    global _RAW_STATE
    try:
        _ = _RAW_STATE
    except NameError:
        _RAW_STATE = {"win": None}
    if _RAW_STATE.get("win") != (w, h):
        _maybe_set_window(w, h)  # best-effort (jeśli brak setterów, po prostu pominie)
        _RAW_STATE["win"] = (w, h)
    _ramwr_safe(buf)  # RAMWR + DATA (one-shot przez nasze _data)


# ponowne zbindowanie na wszelki wypadek
try:
    _ = LCDRenderer
    LCDRenderer.push_frame = _force_push_frame
    low = getattr(LCDRenderer, "raw", None)
    if low is not None:
        low.push_frame = _force_push_frame
except Exception as e:
    print("[force] patch push_frame rebind failed:", e)
# === OVERRIDE: prefer write/writebytes2; chunk fdwrite/xfer to avoid EMSGSIZE ==

try:
    _ = _SPI_CHUNK
except NameError:
    _SPI_CHUNK = 32768  # konserwatywnie


def _spi_best_writer(spi):  # OVERRIDE
    if hasattr(spi, "write"):
        return ("write", spi.write)
    if hasattr(spi, "writebytes2"):
        return ("writebytes2", spi.writebytes2)
    # fdwrite tylko jako fallback (z chunkowaniem w _data)
    try:
        fd = spi.fileno()
        if isinstance(fd, int) and fd > 0:
            return ("fdwrite", lambda b: _os.write(fd, b))
    except Exception:
        pass
    if hasattr(spi, "xfer3"):
        return ("xfer3", spi.xfer3)
    if hasattr(spi, "xfer2"):
        return ("xfer2", spi.xfer2)
    if hasattr(spi, "writebytes"):
        return ("writebytes", spi.writebytes)
    return (None, None)


def _data(bs: bytes):  # OVERRIDE
    _dc_high_guarded()
    spi = _RAWSPI["spi"]
    kind, send = _spi_best_writer(spi)
    if not _RAW_DBG_ONCE["done"]:
        print(f"[raw] path={kind or 'NONE'}", flush=True)
        _RAW_DBG_ONCE["done"] = True
    mv = memoryview(bs)
    if kind in ("write", "writebytes2"):
        send(mv)  # jeden strzał
    elif kind == "fdwrite":
        n = len(mv)
        i = 0
        while i < n:
            j = i + _SPI_CHUNK
            send(mv[i:j])
            i = j
    elif kind in ("xfer3", "xfer2"):
        step = min(_SPI_CHUNK, 4096)
        n = len(mv)
        i = 0
        while i < n:
            j = i + step
            send(list(mv[i:j]))
            i = j
    else:
        send(list(mv))


# ==============================================================================
# ---- RAW CASET/RASET fallback (pełnoekranowe okno) ----------------------------
def _set_window_raw(x0: int, y0: int, x1: int, y1: int):
    # 0x2A = CASET, 0x2B = RASET, 16-bit big-endian
    def _u16be(v):
        return bytes(((v >> 8) & 0xFF, v & 0xFF))

    # CASET
    _send_command_byte(0x2A)
    _data(_u16be(x0) + _u16be(x1))
    # RASET
    _send_command_byte(0x2B)
    _data(_u16be(y0) + _u16be(y1))


# Podmień/miej fallback w helperze okna:
def _maybe_set_window(w: int, h: int):
    # najpierw wysokopoziomowe API, jeśli istnieje
    for fname in ("_set_window", "set_window", "window", "SetWindow", "setwin", "win"):
        fn = globals().get(fname)
        if callable(fn):
            for args in ((0, 0, w - 1, h - 1), (0, w - 1, 0, h - 1), (0, w - 1, h - 1, 0)):
                try:
                    fn(*args)
                    return True
                except Exception:
                    pass
    # klasyczne pary, jeśli istnieją
    caset = globals().get("_caset")
    raset = globals().get("_raset")
    if callable(caset) and callable(raset):
        try:
            caset(0, w - 1)
            raset(0, h - 1)
            return True
        except Exception:
            pass
    # ostateczny, zawsze dostępny fallback: surowe CASET/RASET
    try:
        _set_window_raw(0, 0, w - 1, h - 1)
        return True
    except Exception:
        return False
