#!/usr/bin/env python3
import argparse, pathlib, importlib, sys, time, os, types
from typing import Optional
from io import BytesIO
from PIL import Image

# --- ŚCIEŻKI ---
def _apply_paths_and_local_pkg():
    repo = pathlib.Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo))  # repo root
    # RIDER_APPS_PATH (np. "_apps:apps")
    for p in os.getenv("RIDER_APPS_PATH","").split(":"):
        p = p.strip()
        if not p: continue
        cand = (repo / p).resolve()
        if cand.exists():
            sys.path.insert(0, str(cand))

    # Wstrzyknij lokalny pakiet 'apps' (by nie brać globalnego z site-packages)
    apps_dir = (repo / "apps").resolve()
    ui_dir   = (apps_dir / "ui").resolve()
    face_dir = (ui_dir / "face").resolve()

    def ensure_pkg(name: str, path: pathlib.Path):
        mod = sys.modules.get(name)
        if mod is None or not isinstance(mod, types.ModuleType):
            mod = types.ModuleType(name)
            sys.modules[name] = mod
        # ustaw ścieżkę pakietu na nasz lokalny katalog
        paths = [str(path)]
        if getattr(mod, "__path__", None):
            # wstaw naszą ścieżkę na początek
            exist = [p for p in list(mod.__path__) if p not in paths]
            paths.extend(exist)
        mod.__path__ = paths
        mod.__file__ = str(path / "__init__.py")
        return mod

    ensure_pkg("apps", apps_dir)
    ensure_pkg("apps.ui", ui_dir)
    ensure_pkg("apps.ui.face", face_dir)

_apply_paths_and_local_pkg()

# --- teraz importujemy nasz renderer pakietowo ---

from apps.ui.face.controller import FaceController  # type: ignore
from apps.hw.sink_lcd import SinkLCD

def save(path: str, data: bytes):
    p = pathlib.Path(path); p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)

def rotate_png_bytes(png: bytes, deg: int) -> bytes:
    if not deg: return png
    im = Image.open(BytesIO(png)).convert("RGB").rotate(deg, expand=True)
    buf = BytesIO(); im.save(buf, "PNG"); return buf.getvalue()

# ===== wysyłka przez stary driver: draw_face(payload) =====
def push_face_api(png: bytes, outfile: str, rotate: int, size: int, fb: str) -> Optional[str]:
    try:
        m = importlib.import_module("services.api_core.face_api")
    except Exception:
        return None
    fn = getattr(m, "draw_face", None)
    if not callable(fn):
        return None

    img = Image.open(BytesIO(png)).convert("RGB")
    if rotate:
        img = img.rotate(rotate, expand=True)

    base = {
        "backend": "lcd",
        "outfile": outfile,
        "rotate": rotate,
        "size": size,
        "fb": fb,
        "source": "new_renderer",
        "mode": "png",
        "passthrough": True,
    }
    variants = [
        ("image",     dict(base, image=img)),
        ("png_bytes", dict(base, png_bytes=png)),
        ("frame_png", dict(base, frame_png=png)),
    ]
    for tag, payload in variants:
        try:
            fn(payload)
            return "face_api:draw_face[%s]" % tag
        except TypeError:
            try:
                fn(png);        return "face_api:draw_face[pos]"
            except Exception:
                try:
                    fn(png=png); return "face_api:draw_face[kw]"
                except Exception:
                    pass
        except Exception:
            continue
    return None
# ===========================================================

def _rgb565(r,g,b): return ((r&0xF8)<<8)|((g&0xFC)<<3)|(b>>3)
def png_to_rgb565(png: bytes, rotate=0, force_size=None):
    im = Image.open(BytesIO(png)).convert('RGB')
    if rotate: im = im.rotate(rotate, expand=True)
    if force_size and im.size != force_size: im = im.resize(force_size, Image.BILINEAR)
    w,h = im.size; out=bytearray(w*h*2); i=0; px=im.load()
    for y in range(h):
        for x in range(w):
            v=_rgb565(*px[x,y]); out[i]=(v>>8)&0xFF; out[i+1]=v&0xFF; i+=2
    return bytes(out)

def push_fb(png: bytes, fb: str, rotate=0, size=240) -> bool:
    try:
        data = png_to_rgb565(png, rotate=rotate, force_size=(size,size))
        with open(fb,'wb',buffering=0) as f: f.write(data)
        return True
    except Exception:
        return False

def push_lcd(png: bytes, outfile: str, fb: str, rotate: int, size: int) -> str:
    how = push_face_api(png, outfile, rotate, size, fb)
    if how: return how
    if push_fb(png, fb, rotate=rotate, size=size): return "fb:%s" % fb
    save(outfile, rotate_png_bytes(png, rotate)); return "file:%s" % outfile

def parse_kv_csv(s: str):
    if not s: return {}
    out={}
    for kv in s.split(","):
        kv=kv.strip()
        if not kv: continue
        k,v = kv.split("=",1); k=k.strip(); v=v.strip()
        try: out[k]=float(v)
        except ValueError: out[k]=v
    return out

def read_float_from_file(path: str, default: float = 0.0) -> float:
    try:
        with open(path, "r") as f:
            txt = f.read().strip()
            if not txt: return default
            return max(0.0, min(1.0, float(txt.split()[0])))
    except Exception:
        return default

def main():
    p = argparse.ArgumentParser(description="Face CLI (nowy renderer + RAW sink LCD)")
    p.add_argument("--expr", default="neutral")
    p.add_argument("--size", type=int, default=240)
    p.add_argument("--fps", type=int, default=20)
    p.add_argument("--backend", choices=["png","lcd"], default="lcd")
    p.add_argument("--outfile", default="/tmp/face.png")
    p.add_argument("--rotate", type=int, choices=[0,90,180,270], default=int(os.getenv("FACE_LCD_ROTATE","0")))
    p.add_argument("--fb", default=os.getenv("FACE_FB","/dev/fb1"))
    p.add_argument("--stats", action="store_true")
    p.add_argument("--gesture", default=None)
    p.add_argument("--gargs", default="")
    p.add_argument("--animate", action="store_true")
    p.add_argument("--secs", type=float, default=0.0)
    p.add_argument("--speaking", type=float, default=0.0)
    p.add_argument("--speaking-pipe", default="")
    p.add_argument("--no-idle", action="store_true")
    p.add_argument("--forever", action="store_true")
    p.add_argument("--method", type=str, default="auto", help="Metoda RAW sinka: auto|rgb565|rgb565_3|push_rgb565|push_frame_rgb565_3")
    p.add_argument("--spi-hz", type=int, default=None)
    p.add_argument("--spi-dev", type=str, default=None)
    args = p.parse_args()
    # Loguj ENV
    print(f"[face_cli2] ENV: LCD_ROTATE={os.environ.get('LCD_ROTATE')}, SPI_HZ={os.environ.get('SPI_HZ')}, LCD_SPI_DEV={os.environ.get('LCD_SPI_DEV')}")
    if args.forever:
        args.animate, args.secs = True, 0.0

    fc = FaceController(size=args.size, fps=args.fps, idle=not args.no_idle)
    fc.set_expr(args.expr)
    if args.speaking: fc.speaking(args.speaking)
    if args.gesture:  fc.do(args.gesture, **parse_kv_csv(args.gargs))

    n=0; t0=time.time(); last=""
    try:
        lcd = None
        while True:
            if args.speaking_pipe:
                fc.speaking(read_float_from_file(args.speaking_pipe, args.speaking))
            png = fc.frame()
            if args.backend == "png":
                stem = pathlib.Path(args.outfile)
                out  = stem.with_name("%s_%04d%s" % (stem.stem, n+1, stem.suffix or ".png"))
                save(str(out), png)
            else:
                # Nowy RAW sink
                if lcd is None:
                    lcd = SinkLCD(width=args.size, height=args.size, rotate=args.rotate, spi_hz=args.spi_hz, spi_dev=args.spi_dev, method=args.method)
                img = Image.open(BytesIO(png)).convert("RGB").resize((args.size, args.size))
                used = lcd.push_auto(img)
                if used == 'pil':
                    print(f'[face_cli2] Fallback: ShowImage(PIL)')
                else:
                    print(f'[face_cli2] RAW path in use: {used}')
            n += 1
            if args.stats and (n % max(1, args.fps*5) == 0):
                dt = time.time() - t0
                print("[stats] frames=%d fps~%.1f" % (n, (n/dt if dt>0 else 0.0)))
            time.sleep(1.0/max(1,args.fps))
    except KeyboardInterrupt:
        print("LCD loop finished.")

if __name__ == "__main__":
    main()
