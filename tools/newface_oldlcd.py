#!/usr/bin/env python3
import sys, os, time, pathlib, importlib.util, argparse
from io import BytesIO
from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parents[1]

# 1) dodaj obie gałęzie, najpierw apps (nowy renderer), potem _apps (stary driver)
for p in (ROOT/"apps", ROOT/"_apps"):
    if p.exists(): sys.path.insert(0, str(p))

# 2) import nowego kontrolera
from apps.ui.face.controller import FaceController  # type: ignore

def find_face_api():
    # szukamy _apps/services/api_core/face_api.py (i ew. alternatyw)
    cands = [
        ROOT/"_apps/services/api_core/face_api.py",
        ROOT/"apps/services/api_core/face_api.py",
    ]
    if not cands[0].exists():
        # fallback: szerokie szukanie w _apps
        for p in ROOT.glob("_apps/**/face_api.py"):
            cands.append(p)
    for path in cands:
        if path.exists():
            spec = importlib.util.spec_from_file_location("_legacy_face_api", str(path))
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)  # type: ignore
                return mod, path
    return None, None

def overlay_debug(png: bytes, rotate: int, fb_size=None):
    im = Image.open(BytesIO(png)).convert("RGB")
    if fb_size:
        W,H = fb_size
        canvas = Image.new("RGB",(W,H),(20,0,40))
        ox=(W-im.width)//2; oy=(H-im.height)//2
        canvas.paste(im,(max(0,ox),max(0,oy)))
        im = canvas
    d = ImageDraw.Draw(im)
    w,h = im.size
    d.line((0,0,w-1,h-1), fill=(255,0,255), width=6)
    d.line((w-1,0,0,h-1), fill=(255,0,255), width=6)
    d.text((10,10),"NEW", fill=(255,0,255))
    if rotate: im = im.rotate(rotate, expand=True)
    buf=BytesIO(); im.save(buf,"PNG"); return buf.getvalue()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fps", type=int, default=int(os.getenv("FACE_FPS","20")))
    ap.add_argument("--size", type=int, default=int(os.getenv("FACE_SIZE","240")))
    ap.add_argument("--expr", default=os.getenv("FACE_EXPR","neutral"))
    ap.add_argument("--rotate", type=int, default=int(os.getenv("FACE_LCD_ROTATE","0")))
    ap.add_argument("--fbw", type=int, default=240)
    ap.add_argument("--fbh", type=int, default=320)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    fc = FaceController(size=args.size, fps=args.fps, idle=True)
    fc.set_expr(args.expr)

    face_api, path = find_face_api()
    if not face_api:
        print("ERR: nie znaleziono _apps/services/api_core/face_api.py")
        sys.exit(1)
    print(f"[bridge] using face_api at: {path}")

    n=0; t0=time.time()
    try:
        while True:
            png = fc.frame()
            if args.debug:
                png = overlay_debug(png, args.rotate, fb_size=(args.fbw,args.fbh))
            # spróbuj kilku nazw funkcji (różne wersje)
            sent = False
            for name in ("render","display","main","run"):
                fn = getattr(face_api, name, None)
                if callable(fn):
                    try:
                        fn({"backend":"lcd","png_bytes":png,"outfile":"/tmp/face.png"})
                        sent = True; break
                    except TypeError:
                        try: fn(png); sent=True; break
                        except Exception: pass
                    except Exception: pass
            if not sent:
                # ostatecznie — nadpisz plik, jeśli Wasz watcher tego używa
                pathlib.Path("/tmp/face.png").write_bytes(png)
            n+=1
            if n % (args.fps*5 or 100)==0:
                dt=time.time()-t0
                print(f"[bridge] frames={n} fps~{n/dt:.1f}")
            time.sleep(1.0/max(1,args.fps))
    except KeyboardInterrupt:
        print("\n[bridge] stopped.")
if __name__=="__main__": main()
