#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import pathlib
import signal
import sys
import time
from io import BytesIO

from PIL import Image, ImageDraw

from apps.ui.face.controller import FaceController  # type: ignore


# --- RIDER_APPS_PATH support ---
def _apply_rider_apps_path():
    try:
        repo_root = pathlib.Path(__file__).resolve().parents[3]
    except Exception:
        repo_root = pathlib.Path.cwd()
    paths = os.getenv("RIDER_APPS_PATH", "")
    for p in paths.split(":") if paths else []:
        p = p.strip()
        if not p:
            continue
        cand = (repo_root / p).resolve()
        if cand.exists():
            sys.path.insert(0, str(cand))


_apply_rider_apps_path()


def _parse_fb_size(env: str | None, default: tuple[int, int]) -> tuple[int, int]:
    if not env:
        return default
    try:
        w, h = env.lower().replace("x", " ").split()
        return int(w), int(h)
    except Exception:
        return default


def rotate_png(png: bytes, deg: int) -> bytes:
    if not deg:
        return png
    im = Image.open(BytesIO(png)).convert("RGB").rotate(deg, expand=True)
    buf = BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def rgb565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def img_to_rgb565(img: Image.Image) -> bytes:
    im = img.convert("RGB")
    w, h = im.size
    out = bytearray(w * h * 2)
    i = 0
    px = im.load()
    for y in range(h):
        for x in range(w):
            v = rgb565(*px[x, y])
            out[i] = (v >> 8) & 0xFF
            out[i + 1] = v & 0xFF
            i += 2
    return bytes(out)


def _load_face_api_module() -> object | None:
    """
    Szuka face_api.py w ścieżkach z RIDER_APPS_PATH (preferuje _apps),
    ładuje moduł BEZPOŚREDNIO z pliku, żeby nie kolidował z nowym 'services'.
    """
    try:
        repo_root = pathlib.Path(__file__).resolve().parents[3]
    except Exception:
        repo_root = pathlib.Path.cwd()

    order = []
    env = os.getenv("RIDER_APPS_PATH", "")
    if env:
        for p in env.split(":"):
            p = p.strip()
            if not p:
                continue
            order.append(repo_root / p)

    # zawsze na koniec spróbuj repo_root (gdy ktoś poda absoluty)
    order.append(repo_root)

    candidates = []
    for base in order:
        cand = base / "services" / "api_core" / "face_api.py"
        if cand.exists():
            candidates.append(cand)

    for path in candidates:
        try:
            spec = importlib.util.spec_from_file_location("_legacy_face_api", str(path))
            if not spec or not spec.loader:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[attr-defined]
            return mod
        except Exception:
            continue
    return None


def push_via_face_api(png: bytes, outfile: str) -> bool:
    mod = _load_face_api_module()
    if not mod:
        return False
    for name in ("render", "display", "main", "run"):
        fn = getattr(mod, name, None)
        if callable(fn):
            try:
                fn({"backend": "lcd", "png_bytes": png, "outfile": outfile})
                return True
            except TypeError:
                # starsza sygnatura? spróbuj prościej
                try:
                    fn(png)
                    return True
                except Exception:
                    pass
            except Exception:
                pass
    return False


def write_framebuffer(rgb565_bytes: bytes, fb: str) -> bool:
    try:
        with open(fb, "wb", buffering=0) as f:
            f.write(rgb565_bytes)
        return True
    except Exception:
        return False


def main():
    backend = os.getenv("FACE_BACKEND", "lcd").lower()
    rotate = int(os.getenv("FACE_LCD_ROTATE", os.getenv("FACE_ROTATE", "0")) or 0)
    size = int(os.getenv("FACE_SIZE", "240") or 240)  # rozmiar buźki (kwadrat)
    fps = int(os.getenv("FACE_FPS", "20") or 20)
    expr = os.getenv("FACE_EXPR", "neutral")
    idle_on = os.getenv("FACE_IDLE", "1") not in ("0", "false", "False", "")
    outfile = os.getenv("FACE_OUTFILE", "/tmp/face.png")
    fbdev = os.getenv("FACE_FB", "/dev/fb1" if os.path.exists("/dev/fb1") else "/dev/fb0")
    fb_w, fb_h = _parse_fb_size(os.getenv("FACE_FB_SIZE"), (size, size))
    debug = os.getenv("FACE_DEBUG", "0") not in ("0", "false", "False", "")
    use_api = os.getenv("FACE_USE_API", "0") not in ("0", "false", "False", "")

    fc = FaceController(size=size, fps=fps, idle=idle_on)
    fc.set_expr(expr)

    running = True

    def _sigint(_s, _f):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _sigint)

    last = time.time()
    n = 0
    last_sink = ""
    print(
        (
            f"[face] backend={backend} fb={fbdev} size={size} "
            f"fb_size={fb_w}x{fb_h} rotate={rotate} expr={expr} use_api={use_api}",
        ),
    )
    while running:
        # 1) render buźki
        png = fc.frame()
        face = Image.open(BytesIO(png)).convert("RGB")

        # 2) kanwa pełnoekranowa (żeby przykryć stare piksele)
        canvas = Image.new("RGB", (fb_w, fb_h), (20, 0, 40) if debug else (8, 36, 70))
        ox = (fb_w - face.width) // 2
        oy = (fb_h - face.height) // 2
        canvas.paste(face, (max(0, ox), max(0, oy)))

        # 3) debug overlay
        if debug:
            d = ImageDraw.Draw(canvas)
            d.line((0, 0, fb_w - 1, fb_h - 1), fill=(255, 0, 255), width=6)
            d.line((fb_w - 1, 0, 0, fb_h - 1), fill=(255, 0, 255), width=6)
            d.text((10, 10), "NEW", fill=(255, 0, 255))

        # 4) obrót
        if rotate:
            canvas = canvas.rotate(rotate, expand=True)

        # 5) wysyłka: face_api (jeśli żądany) -> fb -> plik
        sink = ""
        if backend == "png":
            with open(outfile, "wb") as f:
                canvas.save(f, "PNG")
            sink = f"file:{outfile}"
        else:
            if use_api and push_via_face_api(png, outfile):
                sink = "face_api"
            else:
                rgb = img_to_rgb565(canvas)
                if write_framebuffer(rgb, fbdev):
                    sink = f"fb:{fbdev}"
                else:
                    with open(outfile, "wb") as f:
                        canvas.save(f, "PNG")
                    sink = f"file:{outfile}"

        if sink != last_sink:
            print(f"[face] sink={sink}")
            last_sink = sink

        n += 1
        time.sleep(1.0 / max(1, fps))
        if time.time() - last >= 5.0:
            print(f"[face] frames={n} ~{fps}fps")
            last = time.time()


if __name__ == "__main__":
    main()
