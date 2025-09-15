#!/usr/bin/env python3
import os, sys, pathlib, importlib, inspect
from io import BytesIO
from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parents[1]
# driver z _apps ma mieć 1. priorytet
os.environ.setdefault("RIDER_APPS_PATH", "_apps:apps")
for p in os.environ["RIDER_APPS_PATH"].split(":"):
    p = p.strip()
    if p:
        sys.path.insert(0, str((ROOT/p).resolve()))

def make_probe_png(w=240, h=320, rotate=270):
    # fioletowe tło + wielki X + napis NEW + czerwona ramka
    im = Image.new("RGB",(w,h),(20,0,40))
    d = ImageDraw.Draw(im)
    d.line((0,0,w-1,h-1), fill=(255,0,255), width=8)
    d.line((w-1,0,0,h-1), fill=(255,0,255), width=8)
    d.text((10,10),"NEW", fill=(255,0,255))
    d.rectangle((4,4,w-5,h-5), outline=(255,0,0), width=6)
    if rotate:
        im = im.rotate(rotate, expand=True)
    buf = BytesIO(); im.save(buf, "PNG"); return buf.getvalue()

def try_call(fn, png):
    # 3 warianty wywołań: dict z png_bytes, samo png, keyword png=
    tries = [
        ("dict", lambda: fn({"backend":"lcd","png_bytes":png,"outfile":"/tmp/face.png"})),
        ("pos",  lambda: fn(png)),
        ("kw",   lambda: fn(png=png)),
    ]
    for tag, call in tries:
        try:
            call()
            return tag
        except TypeError:
            continue
        except Exception:
            continue
    return None

def main():
    try:
        m = importlib.import_module("services.api_core.face_api")
    except Exception as e:
        print("ERR: nie mogę zaimportować services.api_core.face_api:", e)
        sys.exit(1)
    print("[probe] module:", getattr(m, "__file__", "?"))

    png = make_probe_png()

    candidates = [n for n in dir(m) if callable(getattr(m,n))]
    # preferowane nazwy
    order = ["render","display","show","push","blit","draw","run","main"]
    # posortuj: preferowane najpierw
    candidates = sorted(set(candidates), key=lambda n: (order.index(n) if n in order else 999, n))

    for name in candidates:
        fn = getattr(m, name)
        try:
            sig = str(inspect.signature(fn))
        except Exception:
            sig = "(?)"
        tag = try_call(fn, png)
        print(f"[probe] {name}{sig} -> {tag or 'NO'}")
        if tag:
            print(f"[probe] SUCCESS via {name} / {tag} — powinieneś widzieć fioletowe 'NEW' na LCD.")
            return 0
    print("[probe] żaden wariant nie zadziałał :(")
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
