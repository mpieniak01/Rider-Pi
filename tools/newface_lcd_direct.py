#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import importlib
import importlib.util
import inspect
import os
import pathlib
import re
import sys
import time
from collections import deque
from io import BytesIO

from PIL import Image

from apps.ui.face.controller import FaceController  # type: ignore

ROOT = pathlib.Path(__file__).resolve().parents[1]


def add_paths():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    for p in os.getenv("RIDER_APPS_PATH", "_apps:apps").split(":"):
        p = p.strip()
        if not p:
            continue
        cand = (ROOT / p).resolve()
        if cand.exists() and str(cand) not in sys.path:
            sys.path.insert(0, str(cand))


add_paths()

# Heurystyki nazw metod do „pushowania” klatek do sterownika
NAME_OK = re.compile(
    r"(img|image|frame|png|rgb|buf|buffer|disp|show|blit|push|draw|render|present|send|write|update|put)",
    re.I,
)
NAME_SKIP = re.compile(r"^(set_|get_|begin$|init$|close$|cleanup$|takeover|setspi)", re.I)


def to_png_bytes(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


_ENC_DBG_SHOWN = {"done": False}


def _enc_dbg(msg):
    if not _ENC_DBG_SHOWN["done"]:
        print(f"[enc] {msg}", flush=True)
        _ENC_DBG_SHOWN["done"] = True


def _bench_rgb565_encoder(img):
    t0 = time.time()
    _ = to_rgb565_bytes(img)
    t1 = time.time()
    return (t1 - t0) * 1000.0


def to_rgb565_bytes(img: Image.Image) -> bytes:
    """Fast RGB->RGB565 (BE): fast565 C ext → NumPy → fallback."""
    im = img.convert("RGB")
    w, h = im.size
    try:
        import fast565

        data = im.tobytes()
        _enc_dbg("fast565 C extension")
        return fast565.pack_rgb24_to_rgb565_be(data, w, h)
    except Exception:
        pass
    try:
        import numpy as np

        arr = np.asarray(im, dtype=np.uint8)
        r = arr[..., 0].astype(np.uint16) >> 3
        g = arr[..., 1].astype(np.uint16) >> 2
        b = arr[..., 2].astype(np.uint16) >> 3
        v = (r << 11) | (g << 5) | b
        _enc_dbg("NumPy vectorized path")
        return v.byteswap().tobytes()
    except Exception:
        pass
    _enc_dbg("SLOW fallback loop")
    px = im.load()
    out = bytearray(w * h * 2)
    i = 0
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            out[i] = (v >> 8) & 0xFF
            out[i + 1] = v & 0xFF
            i += 2
    return bytes(out)


def _try_import(modname: str):
    try:
        return importlib.import_module(modname)
    except Exception:
        return None


def import_face_renderers_from_file_first():
    for name in (
        "apps.ui.face.driver_ili9xx",
        "apps.ui.face_renderers",
        "_apps.ui.face_renderers",
    ):
        m = _try_import(name)
        if m is not None:
            return m
    raise ImportError(
        "Nie udało się załadować żadnego modułu sterownika LCD (apps/ui/face/* ani _apps/ui/face_renderers.py)."
    )


class LCDDirect:
    def __init__(
        self,
        rotate: int,
        size: int,
        spi_hz: int | None = None,
        bl_pin: int = 13,
        force: str | None = None,
    ):
        self.rotate = rotate
        self.size = size
        self.spi_hz = spi_hz
        self.bl_pin = bl_pin
        self.force = force
        self._lcd = None
        self._push = None  # (target, name, tag)
        self._disp_wh = (240, 320)
        self._canvas = None
        if not (self.force and self.force.lower() == "pil"):
            self._init_lcd()

    def _build_cfg(self, m):
        FC = getattr(m, "FaceConfig", None)
        if FC is None or not dataclasses.is_dataclass(FC):
            return None
        try:
            cfg = FC()
        except TypeError:
            cfg = object.__new__(FC)
        fields = {f.name for f in dataclasses.fields(FC)}

        def setf(n, v):
            if n in fields:
                setattr(cfg, n, v)

        setf("lcd_do_init", True)
        setf("lcd_rotate", self.rotate)
        setf("lcd_spi_hz", self.spi_hz)
        setf("lcd_bl_pin", self.bl_pin)
        setf("takeover_mode", "pkill")
        setf("takeover_regex", r"apps.ui.face|face_cli2.py|face_fb_loop.py|st77|st7789")
        setf("backend_env", "lcd")
        return cfg

    def _size_from(self, obj):
        for wname, hname in (("width", "height"), ("WIDTH", "HEIGHT"), ("w", "h")):
            w = getattr(obj, wname, None)
            h = getattr(obj, hname, None)
            if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
                return (w, h)
        return None

    def _init_lcd(self):
        m = import_face_renderers_from_file_first()
        print(f"[LCD] driver module: {getattr(m, '__file__', '?')}", flush=True)
        cls = getattr(m, "LCDRenderer", None)
        if cls is None:
            for n, o in vars(m).items():
                if inspect.isclass(o) and ("LCD" in n or "St77" in n or "Renderer" in n):
                    cls = o
                    break
        if cls is None:
            raise RuntimeError("Brak klasy sterownika LCD.")
        try:
            need_cfg = list(inspect.signature(cls.__init__).parameters.keys())[1] == "cfg"
        except Exception:
            need_cfg = False
        if need_cfg:
            cfg = self._build_cfg(m)
            if cfg is None:
                raise RuntimeError("Wymagany cfg")
            self._lcd = cls(cfg)
        else:
            try:
                self._lcd = cls(
                    lcd_do_init=True,
                    lcd_rotate=self.rotate,
                    lcd_spi_hz=self.spi_hz,
                    lcd_bl_pin=self.bl_pin,
                )
            except TypeError:
                try:
                    self._lcd = cls(self.rotate)
                except Exception:
                    self._lcd = cls()
        begin = getattr(self._lcd, "begin", None)
        if callable(begin):
            try:
                begin()
            except Exception:
                pass
        if self.spi_hz and hasattr(self._lcd, "set_spi_speed"):
            try:
                self._lcd.set_spi_speed(self.spi_hz)
            except Exception:
                pass
        wh = self._size_from(self._lcd)
        if not wh:
            for n in ("renderer", "lcd", "device", "driver", "screen", "panel", "disp", "display"):
                sub = getattr(self._lcd, n, None)
                if sub:
                    wh = self._size_from(sub)
                    if wh:
                        break
        if wh:
            self._disp_wh = wh
        print(
            f"[LCD] init ok: rotate={self.rotate} spi_hz={self.spi_hz} bl_pin={self.bl_pin}",
            flush=True,
        )
        print(f"[LCD] disp size: {self._disp_wh[0]}x{self._disp_wh[1]}", flush=True)

    def _targets(self):
        t = [self._lcd]
        for n in ("renderer", "lcd", "device", "driver", "screen", "panel", "disp", "display"):
            sub = getattr(self._lcd, n, None)
            if sub is not None:
                t.append(sub)
        return t

    def _prep(self, img: Image.Image) -> Image.Image:
        if self.rotate:
            rot = {90: Image.ROTATE_90, 180: Image.ROTATE_180, 270: Image.ROTATE_270}.get(
                self.rotate
            )
            img = img.transpose(rot) if rot else img.rotate(self.rotate, expand=True)
        W, H = self._disp_wh
        if img.size != (W, H):
            if self._canvas is None or self._canvas.size != (W, H):
                self._canvas = Image.new("RGB", (W, H), img.getpixel((0, 0)))
            x = (W - img.width) // 2
            y = (H - img.height) // 2
            self._canvas.paste(img, (x, y))
            return self._canvas
        return img

    def _force_bind(self, img: Image.Image) -> bool:
        if not self.force:
            return False
        want = self.force
        if ":" in want:
            name, tag = want.split(":", 1)
        else:
            name, tag = want, "pil"
        for target in self._targets():
            fn = getattr(target, name, None)
            if callable(fn):
                self._push = (target, name, tag)
                print("LCD(direct): FORCED", f"{type(target).__name__}.{name}[{tag}]", flush=True)
                return True
        print(
            f"[LCD] --force requested '{name}', nie znaleziono na obiektach sterownika.", flush=True
        )
        return False

    def _scan_bind(self, img: Image.Image) -> str | None:
        PNG = to_png_bytes(img)
        RGB = to_rgb565_bytes(img)
        w, h = img.size
        tried = []
        for target in self._targets():
            for name in dir(target):
                if name.startswith("_") or NAME_SKIP.search(name) or not NAME_OK.search(name):
                    continue
                fn = getattr(target, name, None)
                if not callable(fn):
                    continue
                variants = [
                    ("pil", (img,), {}),
                    ("pil_kw", (), {"image": img}),
                    ("png", (PNG,), {}),
                    ("png_kw", (), {"png": PNG}),
                    ("png_kw2", (), {"frame_png": PNG}),
                    ("rgb565", (RGB,), {}),
                    ("rgb565_kw", (), {"data": RGB}),
                    ("rgb565_kw2", (), {"buf": RGB}),
                    ("rgb565_3", (w, h, RGB), {}),
                ]
                for tag, a, kw in variants:
                    try:
                        fn(*a, **kw)
                        self._push = (target, name, tag)
                        return f"{type(target).__name__}.{name}[{tag}]"
                    except Exception:
                        tried.append(f"{type(target).__name__}.{name}:{tag}")
                        continue
        print("[LCD] tried:", ", ".join(tried[:16]), "..." if len(tried) > 16 else "", flush=True)
        return None

    def push(self, pil_img: Image.Image) -> str:
        img = self._prep(pil_img)

        if self._push is None:
            if not self._force_bind(img):
                used = self._scan_bind(img)
                if not used:
                    raise RuntimeError("Nie znalazłem metody pushowania.")
                print("LCD(direct): using", used, flush=True)

        target, name, tag = self._push

        if (self.force is None) and tag.startswith("rgb565"):
            try:
                probe_img = img if img.size == (240, 320) else img.resize((240, 320))
            except Exception:
                probe_img = img
            enc_ms = _bench_rgb565_encoder(probe_img)
            if enc_ms > 30.0:
                for cand in ("ShowImage", "show", "present", "blit", "display", "update"):
                    fn = getattr(target, cand, None)
                    if callable(fn):
                        self._push = (target, cand, "pil")
                        name, tag = cand, "pil"
                        print(
                            f"[auto] encoder {enc_ms:.1f} ms → switch to {type(target).__name__}.{name}[{tag}]",
                            flush=True,
                        )
                        break

        fn = getattr(target, name)
        if tag.startswith("pil"):
            fn(img)
        elif tag.startswith("png"):
            PNG = to_png_bytes(img)
            if tag == "png":
                fn(PNG)
            elif tag == "png_kw":
                fn(png=PNG)
            else:
                fn(frame_png=PNG)
        else:
            RGB = to_rgb565_bytes(img)
            w, h = img.size
            if tag == "rgb565":
                fn(RGB)
            elif tag == "rgb565_kw":
                fn(data=RGB)
            elif tag == "rgb565_kw2":
                fn(buf=RGB)
            else:
                fn(w, h, RGB)
        return f"{type(target).__name__}.{name}[{tag}]"


def _parse_mood_seq(s: str | None) -> deque[str]:
    if not s:
        return deque()
    items = [x.strip().lower() for x in s.split(",") if x.strip()]
    items = [x for x in items if x in ("happy", "neutral", "sad")]
    return deque(items)


def _safe_mood_interval(user_interval: float | None) -> float:
    """Dla zbyt małego interwału przyjmij minimum zapewniające domknięcie kroku."""
    step = float(os.getenv("FACE_TRANS_STEP_S", "0.35"))
    dwell = float(os.getenv("FACE_TRANS_DWELL_S", "0.18"))
    if user_interval is None:
        return max(step + dwell, 0.12)
    if user_interval <= 0.0:
        return max(step + dwell, 0.12)
    return user_interval


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expr", default="neutral", help="Wyraz buźki: neutral, happy, sad")
    ap.add_argument("--size", type=int, default=240, help="Rozmiar buźki (px)")
    ap.add_argument("--fps", type=int, default=20, help="Docelowy FPS")
    ap.add_argument(
        "--rotate",
        type=int,
        choices=[0, 90, 180, 270],
        default=int(os.getenv("FACE_LCD_ROTATE", "0")),
        help="Rotacja LCD",
    )
    ap.add_argument(
        "--spi-hz",
        type=int,
        default=int(os.getenv("FACE_LCD_SPI_HZ", "0")) or None,
        help="Prędkość SPI",
    )
    ap.add_argument(
        "--bl-pin",
        type=int,
        default=int(os.getenv("FACE_LCD_BL_PIN", "13")),
        help="Pin podświetlenia",
    )
    ap.add_argument(
        "--force",
        help="Wymuś metodę sterownika LCD, np. push_rgb565:rgb565 / push_pil:pil / raw / pil",
    )
    ap.add_argument("--force-raw", action="store_true", help="Wymuś tryb RAW (jeśli wspierane)")
    ap.add_argument("--force-pil", action="store_true", help="Wymuś tryb PIL (fallback)")
    ap.add_argument("--stats", action="store_true", help="Loguj FPS/statystyki")
    ap.add_argument(
        "--secs",
        type=float,
        default=None,
        help="Czas trwania testu w sekundach (domyślnie: nieskończoność)",
    )

    # Sterowanie „nastrojem” (mood) i sekwencjami
    ap.add_argument(
        "--mood", choices=["happy", "neutral", "sad"], help="Zaplanuj przejście nastroju (ust)."
    )
    ap.add_argument(
        "--mood-via-neutral",
        dest="mood_via_neutral",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Wymuszaj przejście happy↔sad przez neutral (domyślnie: tak).",
    )
    ap.add_argument(
        "--mood-dwell",
        type=float,
        default=os.getenv("FACE_TRANS_DWELL_S"),
        help="Pauza w neutral podczas zmiany biegunów (sek). Domyślnie z ENV FACE_TRANS_DWELL_S lub 0.18.",
    )
    ap.add_argument(
        "--mood-seq",
        type=str,
        default=os.getenv("FACE_MOOD_SEQ", ""),
        help='Sekwencja nastrojów, np. "happy,neutral,sad". Będzie powtarzana cyklicznie.',
    )
    ap.add_argument(
        "--mood-interval",
        type=float,
        default=float(os.getenv("FACE_MOOD_INTERVAL", "1.2")),
        help="Co ile sekund podawać kolejny nastrój z sekwencji (<=0 → auto-min bezpieczny).",
    )

    args = ap.parse_args()

    # Obsługa aliasów force-raw/force-pil
    force = args.force
    if args.force_raw:
        force = "raw"
    elif args.force_pil:
        force = "pil"

    fc = FaceController(size=args.size, fps=args.fps, idle=True)
    fc.set_expr(args.expr)

    # Ustaw nastroje na starcie (pozwala zademonstrować od razu)
    if args.mood:
        print(
            f"[mood] schedule → {args.mood} (via_neutral={args.mood_via_neutral}, dwell={args.mood_dwell})",
            flush=True,
        )
        fc.set_mood(args.mood, via_neutral=args.mood_via_neutral, dwell_s=args.mood_dwell)

    mood_seq = _parse_mood_seq(args.mood_seq)
    mood_interval = _safe_mood_interval(args.mood_interval)
    next_mood_ts = time.time() + mood_interval if mood_seq else float("inf")

    # PIL-only ścieżka
    if force and force.lower() == "pil":
        n = 0
        t0 = time.time()
        last_stats = t0
        try:
            while True:
                now = time.time()
                if args.secs is not None and (now - t0) >= args.secs:
                    print("[PIL] Osiągnięto limit czasu --secs, kończę pętlę.", flush=True)
                    break

                # Sekwencja nastrojów: podawaj tylko gdy idle
                if now >= next_mood_ts and mood_seq:
                    if fc.is_mood_idle():
                        m = mood_seq[0]
                        mood_seq.rotate(-1)
                        print(f"[mood] next → {m}", flush=True)
                        fc.set_mood(m, via_neutral=args.mood_via_neutral, dwell_s=args.mood_dwell)
                        next_mood_ts = now + mood_interval
                    else:
                        # Odłóż do następnej próby
                        next_mood_ts = now + 0.05

                try:
                    img = fc.frame_image().convert("RGB")
                except Exception:
                    frame = fc.frame()
                    img = Image.open(BytesIO(frame)).convert("RGB")
                _ = to_png_bytes(img)
                n += 1
                if args.stats and (now - last_stats) >= 1.0:
                    dt = now - t0
                    print(
                        f"[stats] frames={n} fps~{(n / dt if dt > 0 else 0):.1f} via PIL",
                        flush=True,
                    )
                    last_stats = now
                time.sleep(1.0 / max(1, args.fps))
        except KeyboardInterrupt:
            print("PIL loop finished.")
        finally:
            t1 = time.time()
            dt = t1 - t0
            if n > 0:
                print(f"[PIL] Statystyki: klatek={n}, czas={dt:.2f}s, FPS={n / dt:.2f}", flush=True)
            else:
                print("[PIL] Brak wygenerowanych klatek.", flush=True)
            if hasattr(fc, "close"):
                try:
                    fc.close()
                except Exception:
                    pass
        return

    # LCD path
    lcd = LCDDirect(
        rotate=args.rotate, size=args.size, spi_hz=args.spi_hz, bl_pin=args.bl_pin, force=force
    )
    n = 0
    t0 = time.time()
    last_stats = t0
    last_used = None
    try:
        while True:
            now = time.time()
            if args.secs is not None and (now - t0) >= args.secs:
                print("[LCD] Osiągnięto limit czasu --secs, kończę pętlę.", flush=True)
                break

            # Sekwencja nastrojów: podawaj tylko gdy idle
            if now >= next_mood_ts and mood_seq:
                if fc.is_mood_idle():
                    m = mood_seq[0]
                    mood_seq.rotate(-1)
                    print(f"[mood] next → {m}", flush=True)
                    fc.set_mood(m, via_neutral=args.mood_via_neutral, dwell_s=args.mood_dwell)
                    next_mood_ts = now + mood_interval
                else:
                    # zajęty — spróbuj za chwilę
                    next_mood_ts = now + 0.05

            try:
                img = fc.frame_image().convert("RGB")
            except Exception:
                frame = fc.frame()
                img = Image.open(BytesIO(frame)).convert("RGB")

            used = lcd.push(img)
            if used != last_used:
                print(f"[LCD] bound → {used}", flush=True)
                last_used = used

            n += 1
            if args.stats and (now - last_stats) >= 1.0:
                dt = now - t0
                print(f"[stats] frames={n} fps~{(n / dt if dt > 0 else 0):.1f} via LCD", flush=True)
                last_stats = now
            time.sleep(1.0 / max(1, args.fps))
    except KeyboardInterrupt:
        print("LCD loop finished.")
    finally:
        t1 = time.time()
        dt = t1 - t0
        if n > 0:
            print(f"[LCD] Statystyki: klatek={n}, czas={dt:.2f}s, FPS={n / dt:.2f}", flush=True)
        else:
            print("[LCD] Brak wygenerowanych klatek.", flush=True)
        for obj in (getattr(lcd, "_lcd", None), fc):
            for name in ("close", "cleanup", "end", "sleep", "off"):
                fn = getattr(obj, name, None)
                if callable(fn):
                    try:
                        fn()
                    except Exception:
                        pass


if __name__ == "__main__":
    main()
