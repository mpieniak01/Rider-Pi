#!/usr/bin/env python3
from __future__ import annotations
import argparse, os, sys, time, importlib, inspect, dataclasses

def add_paths():
    import pathlib
    ROOT = pathlib.Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(ROOT), str(ROOT/"apps")]
add_paths()

def _maybe_faceconfig(fr):
    FC = getattr(fr, "FaceConfig", None)
    return FC if (FC and dataclasses.is_dataclass(FC)) else None

def _list_lcd_classes(fr):
    classes=[]
    for name, obj in vars(fr).items():
        if inspect.isclass(obj) and obj.__module__ == fr.__name__:
            has_show = any(callable(getattr(obj,m,None)) for m in ("ShowImage","show_image","display","blit","put","present"))
            has_raw  = all(hasattr(obj,m) for m in ("SetWindows","command","spi_writebyte"))
            if has_show or has_raw or name.lower().startswith("lcd"):
                classes.append(obj)
    return classes

def _pick_lcd_class(fr, prefer=None):
    if prefer:
        for c in _list_lcd_classes(fr):
            if c.__name__ == prefer: return c
        raise AttributeError(f"Nie znaleziono klasy '{prefer}'. Dostępne: {[c.__name__ for c in _list_lcd_classes(fr)]}")
    return getattr(fr,"LCDRenderer",None) or (_list_lcd_classes(fr)[0])

def _build_lcd(fr, drv_rotate, prefer=None):
    cls = _pick_lcd_class(fr, prefer)
    spi_hz = int(os.getenv("FACE_LCD_SPI_HZ","0") or 0)
    bl_pin = int(os.getenv("FACE_LCD_BL_PIN","13"))
    FC = _maybe_faceconfig(fr)
    if FC:
        try:
            try: cfg=FC()
            except TypeError: cfg=object.__new__(FC)
            for n,v in dict(lcd_do_init=True,lcd_rotate=drv_rotate,lcd_spi_hz=spi_hz,lcd_bl_pin=bl_pin).items():
                if any(f.name==n for f in dataclasses.fields(FC)): setattr(cfg,n,v)
            inst = cls(cfg)
        except Exception:
            inst = None
    else:
        inst = None
    if inst is None:
        try:
            inst = cls(lcd_do_init=True, lcd_rotate=drv_rotate, lcd_spi_hz=spi_hz, lcd_bl_pin=bl_pin)
        except Exception:
            try: inst = cls(drv_rotate)
            except Exception: inst = cls()
    dev = getattr(inst,"device",inst)
    try:
        if hasattr(dev,"SPI") and spi_hz: dev.SPI.max_speed_hz = spi_hz
    except Exception:
        pass
    # wymiary
    W = getattr(inst,"width", getattr(dev,"width",240))
    H = getattr(inst,"height",getattr(dev,"height",320))
    return inst, dev, int(W), int(H)

def _try_face_frame(expr, size):
    try:
        fc_mod = importlib.import_module("apps.ui.face.controller")
        FC = getattr(fc_mod,"FaceController")
        fc = FC(size=size, fps=1, idle=True); fc.set_expr(expr)
        def _get():
            try:
                img = fc.frame_image().convert("RGB")
            except Exception:
                from io import BytesIO
                data = fc.frame()
                from PIL import Image
                img = Image.open(BytesIO(data)).convert("RGB")
            return img
        return _get
    except Exception:
        # testcard
        from PIL import Image, ImageDraw
        def _mk(W=240,H=320):
            img = Image.new("RGB",(W,H),(0,0,64))
            drw = ImageDraw.Draw(img)
            cols=[(255,0,0),(0,255,0),(0,0,255),(255,255,0),(255,0,255),(0,255,255),(255,255,255)]
            bw=W//len(cols)
            for i,c in enumerate(cols):
                drw.rectangle([i*bw,0,(i+1)*bw-1,H//2], fill=c)
            drw.rectangle([0,0,W-1,H-1], outline=(255,255,255))
            drw.line([(0,H//2),(W-1,H//2)], fill=(255,255,255))
            drw.line([(W//2,0),(W//2,H-1)], fill=(255,255,255))
            return img
        return lambda: _mk(size, int(size*4/3))

def _to_rgb565(img, bgr=False, byteswap=False):
    rgb = img.convert("RGB"); px = rgb.tobytes()
    data = bytearray(img.width*img.height*2); di=0
    if not bgr:
        for i in range(0,len(px),3):
            r,g,b = px[i], px[i+1], px[i+2]
            v = ((r & 0xF8)<<8) | ((g & 0xFC)<<3) | (b>>3)
            if byteswap: data[di]=v&0xFF; data[di+1]=(v>>8)&0xFF
            else:        data[di]=(v>>8)&0xFF; data[di+1]=v&0xFF
            di+=2
    else:
        for i in range(0,len(px),3):
            r,g,b = px[i], px[i+1], px[i+2]
            v = ((b & 0xF8)<<8) | ((g & 0xFC)<<3) | (r>>3)
            if byteswap: data[di]=v&0xFF; data[di+1]=(v>>8)&0xFF
            else:        data[di]=(v>>8)&0xFF; data[di+1]=v&0xFF
            di+=2
    return data

def main():
    ap = argparse.ArgumentParser(description="Prosty renderer LCD (apps/* only).")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--lcd-class")
    ap.add_argument("--expr", default="neutral")
    ap.add_argument("--img")
    ap.add_argument("--size", type=int, default=240)
    ap.add_argument("--rotate", type=int, choices=[0,90,180,270], default=270)
    ap.add_argument("--fps", type=int, default=20)
    ap.add_argument("--secs", type=float, default=6.0)
    args = ap.parse_args()

    fr = importlib.import_module("apps.ui.face_renderers")

    if args.list:
        names = ", ".join(c.__name__ for c in _list_lcd_classes(fr)) or "(brak)"
        print(f"[clean] dostępne klasy LCD: {names}")
        return

    drv_rotate = int(os.getenv("FACE_LCD_ROTATE","0") or 0)
    inst, dev, W, H = _build_lcd(fr, drv_rotate, args.lcd_class)
    print(f"[clean] lcd_class={inst.__class__.__name__} drv_rotate={drv_rotate} disp={W}x{H}")

    # źródło klatek
    if args.img:
        from PIL import Image
        if os.path.exists(args.img):
            im0 = Image.open(args.img).convert("RGB")
            get_frame = lambda: im0.copy()
        else:
            print("[clean] --img nie istnieje, używam planszy testowej")
            get_frame = _try_face_frame(args.expr, args.size)
    else:
        get_frame = _try_face_frame(args.expr, args.size)

    # Czy mamy natywne ShowImage?
    show_fn = None
    for obj in (inst, dev):
        for name in ("ShowImage","show_image","display","blit","put","present"):
            fn = getattr(obj, name, None)
            if callable(fn):
                show_fn = (obj, fn); break
        if show_fn: break

    use_raw_env = bool(int(os.getenv("FACE_FORCE_RAW","0") or 0))
    has_raw = all(hasattr(dev, m) for m in ("SetWindows","command","spi_writebyte"))
    force_raw = use_raw_env and has_raw
    bgr = bool(int(os.getenv("FACE_BGR","0") or 0))
    bsw = bool(int(os.getenv("FACE_BYTESWAP","0") or 0))

    t0=time.time(); n=0
    try:
        while True:
            if args.secs and (time.time()-t0)>=args.secs: break
            img = get_frame()

            # soft-rotacja
            if args.rotate:
                from PIL import Image
                rot_map={90:Image.ROTATE_90,180:Image.ROTATE_180,270:Image.ROTATE_270}
                op=rot_map.get(args.rotate)
                img = img.transpose(op) if op else img.rotate(args.rotate, expand=True)

            if img.size != (W,H):
                from PIL import Image
                img = img.resize((W,H), Image.BILINEAR)

            if force_raw:
                payload = _to_rgb565(img, bgr=bgr, byteswap=bsw)
                dev.SetWindows(0,0,W-1,H-1)
                dev.command(0x2C)
                chunk = int(os.getenv("FACE_SPI_CHUNK","4096") or 4096)
                for off in range(0, len(payload), chunk):
                    dev.spi_writebyte(payload[off:off+chunk])
            else:
                if show_fn is None:
                    # awaryjnie RAW, jeśli się da
                    if not has_raw:
                        raise RuntimeError("Brak ShowImage i RAW prymitywów w klasie LCD")
                    payload = _to_rgb565(img, bgr=bgr, byteswap=bsw)
                    dev.SetWindows(0,0,W-1,H-1)
                    dev.command(0x2C)
                    chunk = int(os.getenv("FACE_SPI_CHUNK","4096") or 4096)
                    for off in range(0, len(payload), chunk):
                        dev.spi_writebyte(payload[off:off+chunk])
                else:
                    _, fn = show_fn
                    fn(img)

            n+=1
            time.sleep(max(0.0, 1.0/max(1,args.fps)))
    except KeyboardInterrupt:
        pass

    dt = max(1e-9, time.time()-t0)
    print(f"[clean] frames={n} time={dt:.2f}s FPS={n/dt:.2f}")
