#!/usr/bin/env python3
import importlib, pathlib, sys
from io import BytesIO
from PIL import Image, ImageDraw

def white_with_blue_border(size=240):
    im = Image.new("RGB",(size,size),(255,255,255))
    d  = ImageDraw.Draw(im)
    d.rectangle((2,2,size-3,size-3), outline=(0,128,255), width=4)
    buf=BytesIO(); im.save(buf, "PNG"); return buf.getvalue()

def main():
    png = white_with_blue_border(240)
    try:
        m = importlib.import_module("services.api_core.face_api")
        for name in ("render","main","run","display"):
            if hasattr(m, name):
                getattr(m, name)({"backend":"lcd","png_bytes":png,"outfile":"/tmp/face.png"})
                print("OK: pushed to LCD via services.api_core.face_api")
                return
        raise ImportError("face_api has no known entrypoints")
    except Exception as e:
        out = pathlib.Path("/tmp/face.png"); out.write_bytes(png)
        print("NOTE: face_api unavailable or failed:", e)
        print("Saved fallback PNG to", out)

if __name__ == "__main__":
    main()
