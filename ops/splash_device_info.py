#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, time, json, subprocess, socket, platform, sys, re
from urllib.request import urlopen, URLError
from typing import Optional  # Py3.9 kompat
from PIL import Image, ImageDraw, ImageFont

# ---------------- KONFIG ----------------
DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

OUT_IMG = os.path.join(DATA_DIR, "splash_device_info.png")
WIDTH   = int(os.getenv("SPLASH_W", 480))
HEIGHT  = int(os.getenv("SPLASH_H", 320))
ROTATE  = int(os.getenv("SPLASH_ROTATE", os.getenv("PREVIEW_ROT", "0")) or 0)
SECS    = float(os.getenv("SPLASH_SECONDS", "8"))
USE     = os.getenv("SPLASH_USE", "auto")      # xgo|pygame|auto
CLEAR   = int(os.getenv("SPLASH_CLEAR", "1"))
FBDEV   = os.getenv("FBDEV", "/dev/fb1" if os.path.exists("/dev/fb1") else "/dev/fb0")

WAIT_IP   = int(os.getenv("SPLASH_WAIT_IP_S", os.getenv("WAIT_IP", "0")))
WAIT_BATT = int(os.getenv("WAIT_BATT", "5"))

LINE_EXTRA = int(os.getenv("SPLASH_LINE_EXTRA", "6"))
IP_SPACER  = int(os.getenv("SPLASH_IP_SPACER", "2"))
KEY_W      = int(os.getenv("SPLASH_KEY_W", "150"))
REFRESH_EVERY = float(os.getenv("SPLASH_REFRESH_EVERY", "0.5"))

# Sterowanie podświetleniem:
# - ustaw XGO_BL_GPIO na nr BCM pinu (np. 0), żeby sterować,
# - ustaw XGO_BL_GPIO=-1 (domyślnie), żeby NIC nie dotykać.
XGO_BL_GPIO = int(os.getenv("XGO_BL_GPIO", "-1"))
RASPI_GPIO_BIN = "raspi-gpio"

LOG = os.path.join(DATA_DIR, "splash_trace.log")
def _log(msg: str) -> None:
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
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()

# ---------------- POMOCNICZE ----------------
def text_size(draw: ImageDraw.ImageDraw, txt: str, font: ImageFont.FreeTypeFont):
    l, t, r, b = draw.textbbox((0, 0), txt, font=font)
    return (r - l, b - t)

def wrap_lines(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int):
    if "(" in text and "\n" not in text:
        text = re.sub(r"\s*\(", "\n(", text, count=1)
    lines = []
    for chunk in text.split("\n"):
        words = chunk.split()
        if not words:
            lines.append("")
            continue
        cur = words[0]
        for w in words[1:]:
            test = cur + " " + w
            if text_size(draw, test, font)[0] <= max_w:
                cur = test
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines

def _strip_parens(text: str) -> str:
    cleaned = re.sub(r"\s*\([^)]*\)", "", text)
    return re.sub(r"\s{2,}", " ", cleaned).strip()

# ---------------- DANE ----------------
def read_os_pretty() -> str:
    try:
        with open("/etc/os-release") as f:
            kv = {}
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    kv[k] = v.strip().strip('"')
        pretty = kv.get("PRETTY_NAME", platform.platform())
    except Exception:
        pretty = platform.platform()
    return _strip_parens(pretty)

def read_temp_c() -> str:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return f"{float(f.read().strip())/1000.0:.1f}"
    except Exception:
        return "?"

def read_battery_once(timeout_s: float = 1.0) -> Optional[str]:
    try:
        with urlopen("http://127.0.0.1:8080/sysinfo", timeout=timeout_s) as r:
            data = json.loads(r.read().decode())
            bp = data.get("battery_pct")
            if bp is not None:
                return str(int(bp))
    except (URLError, OSError, ValueError, TimeoutError):
        pass
    return None

def pick_battery_nonblocking() -> str:
    t_end = time.time() + max(0, WAIT_BATT)
    while True:
        b = read_battery_once(timeout_s=1.0)
        if b is not None:
            return b
        if time.time() >= t_end:
            return "—"
        time.sleep(0.5)

def _get_ipv4() -> Optional[str]:
    try:
        out = subprocess.check_output(
            ["ip","-4","route","get","1.1.1.1"],
            text=True, stderr=subprocess.DEVNULL
        )
        m = re.search(r"\bsrc (\d+\.\d+\.\d+\.\d+)\b", out or "")
        if m and m.group(1) != "127.0.0.1":
            _log(f"IP via route: {m.group(1)}")
            return m.group(1)
    except Exception as e:
        _log(f"route-get fail: {e}")

    try:
        toks = subprocess.check_output(["hostname","-I"], text=True, stderr=subprocess.DEVNULL).strip().split()
        for t in toks:
            if re.match(r"^\d+\.\d+\.\d+\.\d+$", t) and not t.startswith("127."):
                _log(f"IP via hostname -I: {t}")
                return t
    except Exception as e:
        _log(f"hostname -I fail: {e}")

    try:
        out = subprocess.check_output(["ip","-4","-brief","addr"], text=True, stderr=subprocess.DEVNULL)
        for ln in out.splitlines():
            parts = ln.split()
            if not parts or parts[0] == "lo":
                continue
            for col in parts[2:]:
                if "/" in col and not col.startswith("127."):
                    ip = col.split("/")[0]
                    _log(f"IP via brief addr: {ip} @ {parts[0]}")
                    return ip
    except Exception as e:
        _log(f"ip -brief fail: {e}")

    return None

def pick_ip_nonblocking() -> str:
    ip = _get_ipv4()
    if ip:
        return ip
    deadline = time.time() + max(0, WAIT_IP)
    while time.time() < deadline:
        ip = _get_ipv4()
        if ip:
            return ip
        time.sleep(1)
    return "—"

def gather_info():
    batt = pick_battery_nonblocking()
    batt_str = f"{batt}%" if batt.isdigit() else batt
    return {
        "Host": socket.gethostname(),
        "Date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "OS": read_os_pretty(),
        "Kernel": platform.release(),
        "Temp CPU": f"{read_temp_c()}°C",
        "Battery": batt_str,
        "IP": pick_ip_nonblocking(),
    }

# ---------------- RENDER ----------------
def draw_splash_with(info: dict, w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h), (0,0,0))
    d = ImageDraw.Draw(img)

    title_font = load_font(28)
    body_font  = load_font(24)
    small_font = load_font(16)
    big_font   = load_font(28)

    margin = 14
    vspace = 10
    key_w  = KEY_W
    text_w = w - margin*2 - key_w

    title = "Rider-Pi — Device Info"
    d.text((margin, margin), title, fill=(255,255,255), font=title_font)
    y = margin + 40 + vspace

    _, body_h  = text_size(d, "Ag", body_font)
    _, small_h = text_size(d, "Ag", small_font)
    _, big_h   = text_size(d, "Ag", big_font)

    for k, v in info.items():
        if k == "Kernel":
            d.text((margin+key_w, y), v, fill=(180,180,180), font=small_font)
            y += small_h + 6 + LINE_EXTRA
            continue

        if k == "OS":
            d.text((margin, y), f"{k}:", fill=(180,200,255), font=body_font)
            lines = wrap_lines(d, v, body_font, text_w)
            for line in lines:
                d.text((margin+key_w, y), line, fill=(220,220,220), font=body_font)
                y += body_h + 4 + LINE_EXTRA
            continue

        if k == "IP":
            y += IP_SPACER
            d.text((margin, y), f"{k}:", fill=(200,220,255), font=big_font)
            d.text((margin+key_w, y), v, fill=(255,255,255), font=big_font)
            y += big_h + 8 + LINE_EXTRA
            continue

        d.text((margin, y), f"{k}:", fill=(180,200,255), font=body_font)
        d.text((margin+key_w, y), v, fill=(220,220,220), font=body_font)
        y += body_h + 8 + LINE_EXTRA

    return img

def maybe_rotate(im: Image.Image) -> Image.Image:
    if ROTATE in (90, 180, 270):
        return im.rotate(ROTATE, expand=True)
    return im

# ---------------- HW: podświetlenie (opcjonalnie) ----------------
def _bl_set(low: bool) -> None:
    if XGO_BL_GPIO < 0:
        return
    try:
        subprocess.check_call(
            [RASPI_GPIO_BIN, "set", str(XGO_BL_GPIO), "op", "dl" if low else "dh"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        _log(f"BL GPIO{XGO_BL_GPIO}: {'LOW' if low else 'HIGH'}")
    except Exception as e:
        _log(f"BL ctrl fail: {e}")

# ---------------- WYŚWIETLANIE ----------------
def have_xgo() -> bool:
    try:
        import xgoscreen.LCD_2inch  # noqa
        return True
    except Exception:
        return False

def show_live_xgo():
    import xgoscreen.LCD_2inch as LCD_2inch

    # Zgaś BL tylko jeśli skonfigurowano GPIO (>=0). Gdy -1 — nic nie tykamy.
    _bl_set(low=True)

    disp = LCD_2inch.LCD_2inch()
    disp.Init()
    disp.clear()

    W = int(getattr(disp, 'W', getattr(disp, 'width', 240)))
    H = int(getattr(disp, 'H', getattr(disp, 'height', 320)))
    target_size = (W, H)

    # czarny start, żeby nie było „brudnego” obrazu
    disp.ShowImage(Image.new("RGB", target_size, (0,0,0)))

    t0 = time.time()
    last_payload = None
    first_frame = True

    while True:
        info = gather_info()
        if info != last_payload:
            img = draw_splash_with(info, WIDTH, HEIGHT)
            img = maybe_rotate(img)
            if img.size != target_size:
                img = img.resize(target_size, Image.BICUBIC)
            disp.ShowImage(img)
            last_payload = info
            if first_frame:
                _bl_set(low=False)  # włącz BL po pierwszym poprawnym kadrze
                first_frame = False

        if time.time() - t0 >= SECS:
            break
        time.sleep(REFRESH_EVERY)

    if CLEAR == 1:
        disp.ShowImage(Image.new("RGB", target_size, (0,0,0)))
        time.sleep(0.1)
    _log("xgo live display OK")
    return True

def have_pygame() -> bool:
    try:
        import pygame  # noqa
        return True
    except Exception:
        return False

def show_live_pygame():
    import pygame
    os.environ.setdefault("SDL_VIDEODRIVER", "fbcon")
    if "FBDEV" in os.environ or os.path.exists(FBDEV):
        os.environ["SDL_FBDEV"] = os.environ.get("FBDEV", FBDEV)
    target_size = (HEIGHT, WIDTH) if ROTATE in (90, 270) else (WIDTH, HEIGHT)

    pygame.init()
    screen = pygame.display.set_mode(target_size, 0, 24)
    screen.fill((0,0,0))
    pygame.display.update()

    t0 = time.time()
    last_payload = None
    while True:
        info = gather_info()
        if info != last_payload:
            im = draw_splash_with(info, WIDTH, HEIGHT)
            im = maybe_rotate(im)
            if im.size != target_size:
                im = im.resize(target_size, Image.BICUBIC)
            surf = pygame.image.fromstring(im.tobytes(), im.size, im.mode)
            screen.blit(surf, (0,0))
            pygame.display.update()
            last_payload = info
        if time.time() - t0 >= SECS:
            break
        time.sleep(REFRESH_EVERY)

    pygame.quit()
    _log("pygame live display OK")
    return True

def main():
    _log(f"start uid={os.getuid()} user={os.getenv('USER')} WAIT_IP={WAIT_IP} WAIT_BATT={WAIT_BATT}")
    png_im = draw_splash_with(gather_info(), WIDTH, HEIGHT)
    maybe_rotate(png_im).save(OUT_IMG)

    ok = False
    use = USE.lower()
    try:
        if not ok and use in ("xgo","auto") and have_xgo():
            ok = show_live_xgo()
        if not ok and use in ("pygame","auto") and have_pygame():
            ok = show_live_pygame()
    except Exception as e:
        _log(f"display fail: {e}")
        ok = False

    if ok:
        _log("render OK")
        print(f"[splash] OK: {OUT_IMG} (rot={ROTATE}°, {SECS}s)")
    else:
        _log("PNG only (no display backend)")
        print(f"[splash] PNG only (no display backend): {OUT_IMG}")
        sys.exit(2)

if __name__ == "__main__":
    main()
