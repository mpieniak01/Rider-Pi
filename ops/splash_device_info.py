#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, time, json, subprocess, socket, platform, sys, re
from urllib.request import urlopen
from urllib.error import URLError
from PIL import Image, ImageDraw, ImageFont

# ---------------- KONFIG ----------------
DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

OUT_IMG = os.path.join(DATA_DIR, "splash_device_info.png")
WIDTH   = int(os.getenv("SPLASH_W", 480))
HEIGHT  = int(os.getenv("SPLASH_H", 320))
ROTATE  = int(os.getenv("SPLASH_ROTATE", os.getenv("PREVIEW_ROT", "0")) or 0)
SECS    = float(os.getenv("SPLASH_SECONDS", "3"))
USE     = os.getenv("SPLASH_USE", "auto")          # xgo|pygame|auto
CLEAR   = int(os.getenv("SPLASH_CLEAR", "0"))      # 1=wyczyść po pokazaniu (xgo)
FBDEV   = os.getenv("FBDEV", "/dev/fb1" if os.path.exists("/dev/fb1") else "/dev/fb0")
WAIT_IP = int(os.getenv("SPLASH_WAIT_IP_S", os.getenv("WAIT_IP", "0")))

LOG = os.path.join(DATA_DIR, "splash_trace.log")
def _log(msg: str):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass

# ---------------- FONT ----------------
FONT_PATH_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
]
def load_font(size: int):
    for p in FONT_PATH_CANDIDATES:
        try: return ImageFont.truetype(p, size)
        except Exception: pass
    return ImageFont.load_default()

# ---------------- DANE ----------------
def read_os_pretty() -> str:
    try:
        with open("/etc/os-release") as f:
            kv = {}
            for line in f:
                if "=" in line:
                    k,v = line.strip().split("=",1)
                    kv[k] = v.strip().strip('"')
        return kv.get("PRETTY_NAME", platform.platform())
    except Exception:
        return platform.platform()

def read_temp_c() -> str:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return f"{float(f.read().strip())/1000.0:.1f}"
    except Exception:
        return "?"

def read_battery() -> str:
    try:
        with urlopen("http://127.0.0.1:8080/sysinfo", timeout=0.5) as r:
            data = json.loads(r.read().decode())
            bp = data.get("battery_pct")
            if bp is not None: return str(int(bp))
    except Exception:
        pass
    return "—"

def _get_ipv4():
    # 1) Najbardziej wiarygodne: trasa do Internetu
    try:
        out = subprocess.check_output(["ip","-4","route","get","1.1.1.1"], text=True)
        m = re.search(r"\bsrc (\d+\.\d+\.\d+\.\d+)\b", out or "")
        if m and m.group(1) != "127.0.0.1":
            _log(f"IP via route: {m.group(1)}")
            return m.group(1)
    except Exception as e:
        _log(f"route-get fail: {e}")

    # 2) hostname -I
    try:
        toks = subprocess.check_output(["hostname","-I"], text=True).strip().split()
        for t in toks:
            if re.match(r"^\d+\.\d+\.\d+\.\d+$", t) and not t.startswith("127."):
                _log(f"IP via hostname -I: {t}")
                return t
    except Exception as e:
        _log(f"hostname -I fail: {e}")

    # 3) ip -brief -4 addr
    try:
        out = subprocess.check_output(["ip","-4","-brief","addr"], text=True)
        for ln in out.splitlines():
            parts = ln.split()
            if not parts or parts[0] == "lo": continue
            for col in parts[2:]:
                if "/" in col and not col.startswith("127."):
                    ip = col.split("/")[0]
                    _log(f"IP via brief addr: {ip} @ {parts[0]}")
                    return ip
    except Exception as e:
        _log(f"ip -brief fail: {e}")

    _log("IPv4 not found")
    return None

def pick_ip() -> str:
    if WAIT_IP and WAIT_IP > 0:
        deadline = time.time() + WAIT_IP
        while time.time() < deadline:
            ip = _get_ipv4()
            if ip: return ip
            time.sleep(1)
    ip = _get_ipv4()
    return ip if ip else "—"

def gather_info():
    return {
        "Host": socket.gethostname(),
        "Date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "OS": read_os_pretty(),
        "Kernel": platform.release(),
        "Temp CPU": f"{read_temp_c()}°C",
        "Battery": f"{read_battery()}%",
        "IP": pick_ip(),   # IP na końcu, wyróżnione
    }

# ---------------- RENDER ----------------
def draw_splash(w: int, h: int) -> Image.Image:
    info = gather_info()
    img = Image.new("RGB", (w, h), (0,0,0))
    d = ImageDraw.Draw(img)

    title_font = load_font(28)
    body_font  = load_font(24)
    small_font = load_font(16)
    big_font   = load_font(28)

    margin = 14
    vspace = 10
    key_w = 140

    title = "Rider-Pi — Device Info"
    d.text((margin, margin), title, fill=(255,255,255), font=title_font)
    y = margin + 40 + vspace

    for k, v in info.items():
        if k == "Kernel":
            d.text((margin+key_w, y), v, fill=(180,180,180), font=small_font)
            y += 22
            continue
        if k == "OS":
            d.text((margin, y), f"{k}:", fill=(180,200,255), font=body_font)
            d.text((margin+key_w, y), v, fill=(220,220,220), font=body_font)
            y += 32
            continue
        if k == "IP":
            y += 14
            d.text((margin, y), f"{k}:", fill=(200,220,255), font=big_font)
            d.text((margin+key_w, y), v, fill=(255,255,255), font=big_font)
            y += 36
            continue
        d.text((margin, y), f"{k}:", fill=(180,200,255), font=body_font)
        d.text((margin+key_w, y), v, fill=(220,220,220), font=body_font)
        y += 32

    return img

def maybe_rotate(im: Image.Image) -> Image.Image:
    if ROTATE in (90, 180, 270):
        return im.rotate(ROTATE, expand=True)
    return im

# ---------------- WYŚWIETLENIE ----------------
def have_xgo() -> bool:
    try:
        import xgoscreen.LCD_2inch  # noqa
        return True
    except Exception:
        return False

def show_xgo(im: Image.Image) -> bool:
    try:
        import xgoscreen.LCD_2inch as LCD_2inch
        disp = LCD_2inch.LCD_2inch()
        disp.Init(); disp.clear()
        W = int(getattr(disp, 'W', getattr(disp, 'width', 240)))
        H = int(getattr(disp, 'H', getattr(disp, 'height', 320)))
        img = im.resize((W,H), Image.BICUBIC)
        disp.ShowImage(img)
        time.sleep(SECS)
        if CLEAR == 1:
            disp.ShowImage(Image.new("RGB",(W,H),(0,0,0)))
            time.sleep(0.1)
        _log("xgo display OK")
        return True
    except Exception as e:
        _log(f"xgo fail: {e}")
        return False

def have_pygame() -> bool:
    try:
        import pygame  # noqa
        return True
    except Exception:
        return False

def show_pygame(im: Image.Image) -> bool:
    try:
        import pygame
        os.environ.setdefault("SDL_VIDEODRIVER", "fbcon")
        if "FBDEV" in os.environ or os.path.exists(FBDEV):
            os.environ["SDL_FBDEV"] = os.environ.get("FBDEV", FBDEV)
        pygame.init()
        surf = pygame.image.fromstring(im.tobytes(), im.size, im.mode)
        screen = pygame.display.set_mode(im.size, 0, 24)
        screen.blit(surf, (0,0))
        pygame.display.update()
        time.sleep(SECS)
        pygame.quit()
        _log("pygame display OK")
        return True
    except Exception as e:
        _log(f"pygame fail: {e}")
        return False

def main():
    _log(f"start uid={os.getuid()} user={os.getenv('USER')} WAIT_IP={WAIT_IP}")
    base = draw_splash(WIDTH, HEIGHT)
    final = maybe_rotate(base)
    final.save(OUT_IMG)
    ok = False
    use = USE.lower()
    if use in ("xgo","auto") and have_xgo():
        ok = show_xgo(final)
    if not ok and use in ("pygame","auto") and have_pygame():
        ok = show_pygame(final)
    if ok:
        _log("render OK")
        print(f"[splash] OK: {OUT_IMG} (rot={ROTATE}°, {SECS}s)")
    else:
        _log("PNG only (no display backend)")
        print(f"[splash] PNG only (no display backend): {OUT_IMG}")
        sys.exit(2)

if __name__ == "__main__":
    main()
