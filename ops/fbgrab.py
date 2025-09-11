#!/usr/bin/env python3
# ops/fbgrab.py
# Zrzut faktycznej zawartości LCD (framebuffer) do JPG.
# - tryb jednorazowy (domyślnie)
# - tryb ciągły (--loop lub SNAP_FB_LOOP=1) co SNAP_FB_EVERY sekund
#
# ENV / argumenty:
#   SNAP_FB_DEV   -> ścieżka do fb (domyślnie /dev/fb1)
#   SNAP_FB_W     -> szerokość (domyślnie 320)
#   SNAP_FB_H     -> wysokość (domyślnie 240)
#   SNAP_OUT      -> plik wyjściowy (domyślnie ~/robot/snapshots/lcd_fb.jpg)
#   SNAP_FB_EVERY -> interwał sekund (domyślnie 1.0)
#   SNAP_FB_ROT   -> 0/90/180/270 (obrót przed zapisem; domyślnie 0)
#   SNAP_FB_FMT   -> 'RGB565' (obsługiwany obecnie)
#
# Przykłady:
#   python3 -u ops/fbgrab.py
#   SNAP_FB_LOOP=1 SNAP_FB_EVERY=0.5 python3 -u ops/fbgrab.py --loop
#   SNAP_FB_DEV=/dev/fb1 SNAP_FB_W=320 SNAP_FB_H=240 python3 -u ops/fbgrab.py

import os, sys, time, argparse
from typing import Tuple
import numpy as np
from PIL import Image

def fb_to_image(dev: str, w: int, h: int, fmt: str = "RGB565") -> Image.Image:
    fmt = fmt.upper()
    if fmt != "RGB565":
        raise ValueError("Aktualnie obsługiwany jest tylko RGB565.")

    need = w * h * 2
    with open(dev, "rb", buffering=0) as f:
        buf = f.read(need)
        if len(buf) < need:
            raise RuntimeError(f"Czytanie {dev}: spodziewano {need} B, otrzymano {len(buf)} B. "
                               "Upewnij się, że SNAP_FB_W/H są poprawne.")

    arr = np.frombuffer(buf, dtype=np.uint16).reshape(h, w)
    # RGB565 -> RGB888
    r = ((arr >> 11) & 0x1F) << 3
    g = ((arr >> 5)  & 0x3F) << 2
    b = (arr & 0x1F) << 3
    rgb = np.dstack([r, g, b]).astype(np.uint8)
    return Image.fromarray(rgb, mode="RGB")

def save_fb(dev: str, w: int, h: int, out_path: str, fmt: str, rot: int = 0) -> str:
    img = fb_to_image(dev, w, h, fmt=fmt)
    if rot in (90, 180, 270):
        # rotate clockwise: PIL rotate is counter-clockwise; use transpose helpers
        if rot == 90:
            img = img.transpose(Image.ROTATE_270)  # cw 90
        elif rot == 180:
            img = img.transpose(Image.ROTATE_180)
        elif rot == 270:
            img = img.transpose(Image.ROTATE_90)   # cw 270
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, "JPEG", quality=85)
    return out_path

def read_env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except Exception:
        return default

def main():
    parser = argparse.ArgumentParser(description="Framebuffer -> JPG (LCD 2\")")
    parser.add_argument("--loop", action="store_true", help="tryb ciągły")
    args = parser.parse_args()

    dev   = os.getenv("SNAP_FB_DEV", "/dev/fb1")
    w     = read_env_int("SNAP_FB_W", 320)
    h     = read_env_int("SNAP_FB_H", 240)
    out   = os.path.expanduser(os.getenv("SNAP_OUT", "~/robot/snapshots/lcd_fb.jpg"))
    every = float(os.getenv("SNAP_FB_EVERY", "1.0"))
    rot   = read_env_int("SNAP_FB_ROT", 0)
    fmt   = os.getenv("SNAP_FB_FMT", "RGB565")
    loop  = args.loop or (os.getenv("SNAP_FB_LOOP", "0") == "1")

    if not os.path.exists(dev):
        print(f"[fbgrab] ERROR: {dev} nie istnieje. Jesteś pewien, że LCD to {dev}?")
        sys.exit(1)

    if loop:
        print(f"[fbgrab] loop: dev={dev} size={w}x{h} fmt={fmt} rot={rot} every={every}s -> {out}")
        while True:
            try:
                path = save_fb(dev, w, h, out, fmt=fmt, rot=rot)
                print(f"[fbgrab] saved: {path}")
            except Exception as e:
                print("[fbgrab] ERROR:", e)
            time.sleep(every)
    else:
        try:
            path = save_fb(dev, w, h, out, fmt=fmt, rot=rot)
            print(f"[fbgrab] saved: {path}")
        except Exception as e:
            print("[fbgrab] ERROR:", e)
            sys.exit(2)

if __name__ == "__main__":
    main()
