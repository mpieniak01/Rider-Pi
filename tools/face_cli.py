#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI for the NEW face renderer (apps/*), using services.api_core.face_api.
- LCD via draw_face(payload=json-string)
- PNG via render_face(payload=json-string) -> save to file
Handles return types: bytes/base64/PIL.Image/dict{image|png|data|bytes|content}
"""
from __future__ import annotations
import argparse, os, sys, inspect, importlib, io, base64, json
from pathlib import Path

def build_parser()->argparse.ArgumentParser:
    p=argparse.ArgumentParser(description="Render the face (new apps/* code)")
    p.add_argument("--backend", choices=["lcd","png"], default="lcd")
    p.add_argument("--rotate  type=int, choices=[0,90,180,270], default=0)
    p.add_argument("--spi-hz", type=int, default=32000000, dest="spi_hz")
    p.add_argument("--guide", action="store_true", help="overlay guides")
    p.add_argument("--state", default="idle")
    p.add_argument("--eyes", default="open")
    p.add_argument("--mouth", default="neutral")
    p.add_argument("--png", type=str, help="Path to output PNG when --backend=png")
    return p

def _set_env(a):
    os.environ["FACE_BACKEND"]=a.backend
    os.environ["FACE_LCD_ROTATE"]=str(a.rotate)
    os.environ["FACE_LCD_SPI_HZ"]=str(int(a.spi_hz))
    if a.guide: os.environ["FACE_GUIDE"]="1"

def _payload(a)->dict:
    return {"backend":a.backend,"rotate":a.rotate,"spi_hz":a.spi_hz,
            "guide":bool(a.guide),"state":a.state,"eyes":a.eyes,"mouth":a.mouth}

def _filter_kwargs(fn, **kw):
    sig = inspect.signature(fn); return {k:v for k,v in kw.items() if k in sig.parameters}

def _as_bytes(obj):
    if isinstance(obj,(bytes,bytearray)): return bytes(obj)
    if isinstance(obj,str):
        try: return base64.b64decode(obj, validate=True)
        except Exception: return None
    if isinstance(obj,dict):
        for k in ("image","png","data","bytes","content"):
            v=obj.get(k)
            if isinstance(v,(bytes,bytearray)): return bytes(v)
            if isinstance(v,str):
                try: return base64.b64decode(v, validate=True)
                except Exception: pass
    return None

def _as_image(obj):
    try:
        from PIL import Image
    except Exception:
        return None
    if 'PIL' in str(type(obj)): return obj
    b=_as_bytes(obj)
    if b:
        try: return Image.open(io.BytesIO(b))
        except Exception: return None
    return None

def _lcd_show(img, rotate:int, spi_hz:int):
    try:
        import xgoscreen.LCD_2inch as L
        lcd=L.LCD_2inch(); lcd.Init()
        W,H=lcd.width,lcd.height
        if img.size!=(W,H): img=img.resize((W,H))
        lcd.ShowImage(img.convert("RGB"))
        print("[OK] LCD via xgoscreen"); return 0
    except Exception:
        try:
            import ST7789
            disp=ST7789.ST7789(port=0, cs=0, dc=25, backlight=13, rst=27,
                               width=240, height=320,
                               rotation=int(rotate), spi_speed_hz=int(spi_hz))
            disp.begin()
            if img.size!=(240,320): img=img.resize((240,320))
            disp.display(img.convert("RGB"))
            print("[OK] LCD via ST7789"); return 0
        except Exception as e2:
            print(f"[ERR] LCD display failed: {e2}", file=sys.stderr); return 1

def main(argv=None)->int:
    a = build_parser().parse_args(argv)
    _set_env(a)

    try:
        m = importlib.import_module("services.api_core.face_api")
    except Exception as e:
        print(f"[ERR] cannot import services.api_core.face_api: {e}", file=sys.stderr)
        return 2

    payload = _payload(a)
    jpayload = json.dumps(payload, separators=(",",":"))

    # 1) LCD via draw_face(payload=json-string)
    if a.backend=="lcd" and hasattr(m,"draw_face") and callable(m.draw_face):
        try:
            try: res = m.draw_face(jpayload)          # positional JSON string
            except TypeError: res = m.draw_face(payload=jpayload)  # keyword
            img = _as_image(res)
            if img is not None: return _lcd_show(img, a.rotate, a.spi_hz)
            pass  # fallback to render_face if nothing was drawn
        except Exception as e:
            print(f"[ERR] draw_face failed: {e}", file=sys.stderr)
            # fall through to render_face

    # 2) PNG/LCD via render_face(payload=json-string) -> bytes/base64/PIL.Image
    if hasattr(m,"render_face") and callable(m.render_face):
        try:
            try: res = m.render_face(jpayload)
            except TypeError: res = m.render_face(payload=jpayload)
        except Exception as e:
            print(f"[ERR] render_face failed: {e}", file=sys.stderr); return 1

        if a.backend=="png":
            out = a.png or "snapshots/face.png"
            img = _as_image(res)
            if img is not None:
                from PIL import Image
                Path(out).parent.mkdir(parents=True, exist_ok=True)
                img.save(out); print(out); return 0
            b = _as_bytes(res)
            if b:
                Path(out).parent.mkdir(parents=True, exist_ok=True)
                with open(out,"wb") as f: f.write(b)
                print(out); return 0
            print("[ERR] render_face returned unsupported type for PNG.", file=sys.stderr)
            return 1
        else:
            img = _as_image(res)
            if img is not None: return _lcd_show(img, a.rotate, a.spi_hz)
            b = _as_bytes(res)
            if b:
                try:
                    from PIL import Image
                    img = Image.open(io.BytesIO(b))
                    return _lcd_show(img, a.rotate, a.spi_hz)
                except Exception as e:
                    print(f"[ERR] cannot decode bytes to image: {e}", file=sys.stderr)
            print("[ERR] render_face produced unsupported type for LCD.", file=sys.stderr)
            return 1

    print("[ERR] face_api has neither draw_face nor render_face callables.", file=sys.stderr)
    return 3

if __name__ == "__main__":
    raise SystemExit(main())
