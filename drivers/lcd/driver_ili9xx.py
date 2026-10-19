from __future__ import annotations

import builtins as _bi
import os
import os as _os
import time as time
from time import time as _time

from drivers.lcd.board import LCDBoard as LCDBoard, lcd_board
from drivers.lcd.ili9xx_device import (
    _PIL_ERR as _PIL_ERR,
    _XGO_ERR as _XGO_ERR,
    Any as Any,
    Callable as Callable,
    FaceConfig as FaceConfig,
    Image as Image,
    LCDRenderer as LCDRenderer,
    _find_presenter as _find_presenter,
    _find_raw_iface as _find_raw_iface,
    _iter_xgo_modules as _iter_xgo_modules,
    _pick_device_class as _pick_device_class,
    _rgb888_to_rgb565 as _rgb888_to_rgb565,
    _score_class as _score_class,
    dataclass as dataclass,
    importlib as importlib,
    inspect as inspect,
    pkgutil as pkgutil,
    xgoscreen as xgoscreen,
)

FaceConfig.__module__ = __name__
LCDRenderer.__module__ = __name__


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


def _try_target_frame(target, w, h, buf):
    for name, dimensions in (
        ("push_rgb565_3", True),
        ("push_frame", True),
        ("blit_rgb565", True),
        ("write_rgb565", True),
        ("push_rgb565", False),
        ("draw565", True),
    ):
        fn = getattr(target, name, None)
        if not callable(fn):
            continue
        try:
            return True, fn(w, h, buf) if dimensions else fn(buf)
        except Exception:
            pass
    return False, None


def _lcd_push_frame(self, w: int, h: int, buf: bytes):
    """Try raw targets in order, then dedicated RGB565 and PIL presentation."""
    for target_name in ("raw", "device", "lcd", "renderer", "panel", "disp", "display"):
        target = getattr(self, target_name, None)
        if target is None:
            continue
        found, result = _try_target_frame(target, w, h, buf)
        if found:
            return result
    fn = getattr(self, "ShowRGB565", None)
    if callable(fn):
        try:
            return fn(w, h, buf)
        except Exception:
            pass
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


class _RawPushPaths:
    """Primitives captured from one low-level device when its fastpath is installed."""

    def __init__(self, low):
        self.set_window = _pick(low, ("set_window", "setaddrwindow", "window"))
        self.write_cmd = _pick(low, ("write_cmd", "cmd", "command", "writecommand"))
        self.write_data = _pick(low, ("write_data", "data", "writedata"))
        self.ramwr = _pick(low, ("ram_write", "ramwr", "memory_write"))
        spi = getattr(low, "spi", None)
        self.spi_write = _pick(spi, ("write", "writebytes", "xfer2")) if spi is not None else None
        self.dc_high = _pick(low, ("dc_high", "dc_on", "datamode"))
        self.dc_low = _pick(low, ("dc_low", "dc_off", "commandmode"))

    def _coordinate(self, command, edge):
        self.write_cmd(command)
        values = [0, 0, 0, edge]
        if self.write_data and self.write_data(bytes(values)):
            return
        # Preserve the established fallback when write_data returns a false value.
        if self.dc_high:
            self.dc_high()
        if self.spi_write:
            self.spi_write(values)

    def _window(self, w, h):
        if self.set_window:
            self.set_window(0, 0, w - 1, h - 1)
        elif self.write_cmd:
            self._coordinate(0x2A, w - 1)
            self._coordinate(0x2B, h - 1)

    def _memory_write_command(self):
        if self.write_cmd:
            self.write_cmd(0x2C)
            return
        if self.dc_low:
            self.dc_low()
        if self.spi_write:
            self.spi_write([0x2C])

    def _send_data(self, buf):
        if self.write_data:
            self.write_data(buf)
        elif self.spi_write:
            if self.dc_high:
                self.dc_high()
            self.spi_write(list(buf) if self.spi_write.__name__ == "xfer2" else buf)
        else:
            raise RuntimeError("No data path for raw push")

    def push(self, w, h, buf):
        self._window(w, h)
        if self.ramwr:
            self.ramwr(buf)
            return
        self._memory_write_command()
        self._send_data(buf)


def _raw_install_push_rgb565_3(root):
    low = _find_ll(root, ("raw", "device", "lcd", "panel", "disp", "display"))
    if low is None:
        return False
    if _pick(low, ("push_rgb565_3", "blit_rgb565", "write_rgb565", "push_frame")):
        return True
    paths = _RawPushPaths(low)
    if not (paths.set_window or (paths.write_cmd and (paths.write_data or paths.spi_write))):
        return False

    def _push_rgb565_3(w: int, h: int, buf: bytes):
        paths.push(w, h, buf)

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

_BOARD = lcd_board()
_DEF_SPI = _BOARD.spi
_DEF_HZ = _BOARD.hz
_DEF_MODE = int(os.getenv("FACE_SPI_MODE", "0") or 0)
_DEF_DC = _BOARD.dc
_DEF_RST = _BOARD.rst

_RAWSPI = {"spi": None, "inited": False}


def _cmd(c: int):
    # DC=0 (command), wyślij 1 bajt
    _GPIO.output(_DEF_DC, _GPIO.LOW)
    spi = _RAWSPI["spi"]
    if hasattr(spi, "writebytes"):
        spi.writebytes([c & 0xFF])
    else:
        spi.xfer2([c & 0xFF])


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


# pokaż raz, którą ścieżkę wybrano
try:
    _ = _RAW_DBG_SHOWN
except NameError:
    _RAW_DBG_SHOWN = {"done": False}


# ==============================================================================
# ==== DIAG: pokaż realny max_speed_hz i ścieżkę wysyłki raz ===================
try:
    _ = _SPI_DBG_ONCE
except NameError:
    _SPI_DBG_ONCE = {"done": False}


try:
    _ = _RAW_DBG_ONCE
except NameError:
    _RAW_DBG_ONCE = {"done": False}


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


# cache okna (CASET/RASET tylko jeśli zmiana rozmiaru)
try:
    _ = _RAW_STATE
except NameError:
    _RAW_STATE = {"win": None}


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
            print(
                (
                    f"[spi] requested_hz={_DEF_HZ} actual_hz={spi.max_speed_hz} ",
                    f"mode={spi.mode} bpw={getattr(spi, 'bits_per_word', 8)}",
                ),
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


# cache window (set once per WxH)
try:
    _ = _RAW_STATE
except NameError:
    _RAW_STATE = {"win": None}


# ==============================================================================


# ---- safe command sender + RAMWR fallback ------------------------------------
def _send_spi_command(kind, send, cmd_val):
    command = memoryview(bytes((cmd_val & 0xFF,)))
    if kind in ("write", "writebytes2"):
        send(command)
    elif kind == "fdwrite":
        return send(command) == 1
    elif kind in ("xfer3", "xfer2", "writebytes"):
        send(list(command))
    else:
        return False
    return True


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
        return _send_spi_command(kind, send, cmd_val)
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
            for args in (
                (0, 0, w - 1, h - 1),
                (0, w - 1, 0, h - 1),
                (0, w - 1, h - 1, 0),
            ):
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
