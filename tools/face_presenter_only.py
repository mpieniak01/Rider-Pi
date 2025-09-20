#!/usr/bin/env python3
import argparse
import importlib
import os
import pkgutil
import sys
import time

from PIL import Image, ImageDraw


def find_presenter():
    xs = importlib.import_module("xgoscreen")
    # 1) bezpośrednio pod xgoscreen
    for name in dir(xs):
        obj = getattr(xs, name)
        if hasattr(obj, "ShowImage"):
            try:
                return obj()
            except Exception:
                pass
    # 2) w podmodułach
    for _, modname, _ in pkgutil.walk_packages(xs.__path__, xs.__name__ + "."):
        try:
            m = importlib.import_module(modname)
        except Exception:
            continue
        for name in dir(m):
            c = getattr(m, name)
            if hasattr(c, "ShowImage"):
                try:
                    return c()
                except Exception:
                    pass
    raise RuntimeError("Nie znalazłem klasy z ShowImage w xgoscreen.*")


def get_size(dev):
    for attr in ("width", "W", "w"):
        w = getattr(dev, attr, None)
        if isinstance(w, int) and w > 0:
            break
    else:
        w = 240
    for attr in ("height", "H", "h"):
        h = getattr(dev, attr, None)
        if isinstance(h, int) and h > 0:
            break
    else:
        h = 320
    return w, h


def make_testcard(w, h):
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    colors = ["red", "green", "blue", "yellow", "magenta", "cyan", "orange"]
    bh = max(1, h // len(colors))
    for i, c in enumerate(colors):
        d.rectangle((0, i * bh, w, (i + 1) * bh - 1), fill=c)
    d.rectangle((0, 0, w - 1, h - 1), outline="white", width=3)
    d.line((0, 0, w - 1, h - 1), fill="white", width=3)
    d.line((0, h - 1, w - 1, 0), fill="white", width=3)
    return img


def get_face_frame(expr: str, size):
    # spróbuj Twojego kontrolera; jeśli go brak – użyj planszy
    try:
        m = importlib.import_module("apps.ui.face_legacy")
        FC = getattr(m, "FaceController")
        fc = FC(expr=expr)
        img = fc.frame_image().convert("RGB")
        return img.resize(size)
    except Exception:
        return make_testcard(*size)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expr", default="neutral")
    ap.add_argument("--rotate", type=int, default=270, choices=(0, 90, 180, 270))
    ap.add_argument("--fps", type=int, default=20)
    ap.add_argument("--secs", type=float, default=10)
    args = ap.parse_args()

    # środowisko (Hz/tryb) – jak u Ciebie działało najlepiej
    hz = int(os.getenv("FACE_LCD_SPI_HZ", "0") or 0)
    mode = int(os.getenv("FACE_SPI_MODE", "0") or 0)

    dev = find_presenter()
    for name in ("begin", "Begin", "Init", "init"):
        fn = getattr(dev, name, None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass

    spi = getattr(dev, "SPI", None)
    if spi is not None:
        try:
            if hz:
                spi.max_speed_hz = hz
            if hasattr(spi, "mode"):
                spi.mode = mode
        except Exception:
            pass

    W, H = get_size(dev)
    period = 1.0 / max(1, args.fps)
    t0 = time.time()
    frames = 0

    while time.time() - t0 < args.secs:
        img = get_face_frame(args.expr, (W, H))
        if args.rotate:
            img = img.rotate(args.rotate, expand=True).resize((W, H))
        dev.ShowImage(img)
        frames += 1
        dt = period - (time.time() - (t0 + frames * period))
        if dt > 0:
            time.sleep(dt)

    print(
        f"[presenter] frames={frames} time={time.time() - t0:.2f}s fps~{frames / max(0.001, (time.time() - t0)):.2f} W={W} H={H} hz={hz} mode={mode}"
    )


if __name__ == "__main__":
    sys.path[:0] = ["/home/pi/robot", "/home/pi/robot/apps"]
    main()
