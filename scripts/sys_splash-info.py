#!/usr/bin/env python3
from __future__ import annotations

import os
import platform
import re
import socket
import subprocess
import sys
import time

from PIL import Image, ImageDraw, ImageFont

# ---------------- KONFIG ----------------
DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# Żeby pod systemd działały importy z projektu (tools.*). NIE używamy services/api_core.
if DIR not in sys.path:
    sys.path.insert(0, DIR)
# pozwól importować moduły przeniesione do scripts/
SCRIPTS_DIR = os.path.join(DIR, "scripts")
if os.path.isdir(SCRIPTS_DIR) and SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

# Load splash configuration from face config
try:
    from apps.ui.face.config import load_config as load_face_config

    _face_cfg = load_face_config()
    _SPLASH_LOGO_DEFAULT = _face_cfg.vendor_splash_logo_path
    _SPLASH_ROTATE_DEFAULT = _face_cfg.splash_lcd_rotate
except ImportError:
    # Fallback to hardcoded defaults if config unavailable
    _SPLASH_LOGO_DEFAULT = os.path.join(DATA_DIR, "splash_logo.png")
    _SPLASH_ROTATE_DEFAULT = 270

OUT_IMG = os.path.join(DATA_DIR, "splash_device_info.png")
WIDTH = int(os.getenv("SPLASH_W", "480"))
HEIGHT = int(os.getenv("SPLASH_H", "320"))
from drivers.lcd.board import lcd_board  # noqa: E402 - repository path is bootstrapped above

ROTATE = lcd_board().rotate
SECS = float(os.getenv("SPLASH_SECONDS", "8"))
USE = os.getenv("SPLASH_USE", "auto")  # xgo|pygame|auto
CLEAR = int(os.getenv("SPLASH_CLEAR", "1"))
FBDEV = os.getenv("FBDEV", "/dev/fb1" if os.path.exists("/dev/fb1") else "/dev/fb0")

# --- PRE-SLIDE (LOGO) ---
SPLASH_LOGO = os.getenv("SPLASH_LOGO", _SPLASH_LOGO_DEFAULT)
try:
    SPLASH_LOGO_SECONDS = float(os.getenv("SPLASH_LOGO_SECONDS", "0") or "0")
except ValueError:
    SPLASH_LOGO_SECONDS = 0.0

WAIT_IP = int(os.getenv("SPLASH_WAIT_IP_S", os.getenv("WAIT_IP", "0")))
WAIT_BATT = int(os.getenv("WAIT_BATT", "3"))
SPLASH_HIDE_EMPTY_BATT = int(os.getenv("SPLASH_HIDE_EMPTY_BATT", "0"))
SPLASH_EARLY_EXIT = int(os.getenv("SPLASH_EARLY_EXIT", "0"))
SHOW_IP_DELAY = int(os.getenv("SHOW_IP_DELAY", "1"))

LINE_EXTRA = int(os.getenv("SPLASH_LINE_EXTRA", "6"))
IP_SPACER = int(os.getenv("SPLASH_IP_SPACER", "2"))
KEY_W = int(os.getenv("SPLASH_KEY_W", "150"))
REFRESH_EVERY = float(os.getenv("SPLASH_REFRESH_EVERY", "0.5"))

# Sterowanie podświetleniem

LOG = os.path.join(DATA_DIR, "splash_trace.log")

# Znaczniki czasu dla IP (pierwsze udane wykrycie)
_START_TS = time.time()  # (pozostaje — już nie używamy do IP)
_IP_FIRST_SEEN_AT: float | None = None  # teraz: sekundy OD STARTU SYSTEMU (uptime)


def _log(msg: str) -> None:
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def _uptime_seconds() -> float:
    """Zwraca sekundy od startu systemu."""
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except Exception:
        return 0.0


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
    left, t, r, b = draw.textbbox((0, 0), txt, font=font)
    return (r - left, b - t)


def wrap_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_w: int,
) -> list[str]:
    if "(" in text and "\n" not in text:
        opening = text.index("(")
        text = text[:opening].rstrip() + "\n" + text[opening:]
    lines: list[str] = []
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
    parts = []
    cursor = 0
    while True:
        opening = text.find("(", cursor)
        if opening < 0:
            break
        closing = text.find(")", opening + 1)
        if closing < 0:
            break
        parts.append(text[cursor:opening].rstrip())
        cursor = closing + 1
    parts.append(text[cursor:])
    cleaned = "".join(parts)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _letterbox_fit(im: Image.Image, target_wh: tuple[int, int]) -> Image.Image:
    """Dopasuj z zachowaniem proporcji (letterbox), bez rozciągania."""
    tw, th = target_wh
    iw, ih = im.size
    if tw <= 0 or th <= 0 or iw <= 0 or ih <= 0:
        return im
    scale = min(tw / iw, th / ih)
    nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
    im2 = im.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGB", (tw, th), (0, 0, 0))
    ox, oy = (tw - nw) // 2, (th - nh) // 2
    canvas.paste(im2, (ox, oy))
    return canvas


# ---------------- DANE ----------------
def read_os_pretty() -> str:
    try:
        with open("/etc/os-release") as f:
            kv: dict[str, str] = {}
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
            return f"{float(f.read().strip()) / 1000.0:.1f}"
    except Exception:
        return "?"


# ---- BATERIA: istniejący, jedyny właściciel UART → snapshot BUS ----
def read_battery_once() -> str | None:
    # Snapshot keeps the original measurement timestamp and ratio unit. Boot
    # before executor/broker intentionally has no battery; never open SDK/UART.
    from apps.safety.state import read_status
    from apps.ui.status_panel import battery_observation

    sample = battery_observation(read_status(), now=time.time())
    if sample.get("ready") is True:
        return f"{sample['value'] * 100:.0f}"
    return None


def pick_battery_nonblocking() -> str:
    # A bounded source wait is allowed only within the configured splash. No
    # cache refresh, voltage guessing or hardware query can invent a reading.
    deadline = time.monotonic() + max(0, WAIT_BATT)
    while True:
        value = read_battery_once()
        if value is not None:
            return value
        if time.monotonic() >= deadline:
            return "—"
        time.sleep(0.1)


def _ipv4_from_route():
    out = subprocess.check_output(
        ["ip", "-4", "route", "get", "1.1.1.1"],
        text=True,
        stderr=subprocess.DEVNULL,
    )
    m = re.search(r"\bsrc (\d+\.\d+\.\d+\.\d+)\b", out or "")
    if m and m.group(1) != "127.0.0.1":
        _log(f"IP via route: {m.group(1)}")
        return m.group(1)
    return None


def _ipv4_from_hostname():
    toks = (
        subprocess.check_output(
            ["hostname", "-I"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        .strip()
        .split()
    )
    for t in toks:
        if re.match(r"^\d+\.\d+\.\d+\.\d+$", t) and not t.startswith("127."):
            _log(f"IP via hostname -I: {t}")
            return t
    return None


def _ipv4_from_brief():
    out = subprocess.check_output(
        ["ip", "-4", "-brief", "addr"],
        text=True,
        stderr=subprocess.DEVNULL,
    )
    for ln in out.splitlines():
        parts = ln.split()
        if not parts or parts[0] == "lo":
            continue
        for col in parts[2:]:
            if "/" in col and not col.startswith("127."):
                ip = col.split("/")[0]
                _log(f"IP via brief addr: {ip} @ {parts[0]}")
                return ip
    return None


def _get_ipv4() -> str | None:
    for resolve, label in (
        (_ipv4_from_route, "route-get fail:"),
        (_ipv4_from_hostname, "hostname -I fail:"),
        (_ipv4_from_brief, "ip -brief fail:"),
    ):
        try:
            address = resolve()
            if address is not None:
                return address
        except Exception as exc:
            _log(f"{label} {exc}")
    return None


def pick_ip_nonblocking() -> str:
    global _IP_FIRST_SEEN_AT
    ip = _get_ipv4()
    if ip:
        if _IP_FIRST_SEEN_AT is None:
            _IP_FIRST_SEEN_AT = _uptime_seconds()  # <-- OD STARTU SYSTEMU
        return ip
    deadline = time.time() + max(0, WAIT_IP)
    while time.time() < deadline:
        ip = _get_ipv4()
        if ip:
            if _IP_FIRST_SEEN_AT is None:
                _IP_FIRST_SEEN_AT = _uptime_seconds()  # <-- OD STARTU SYSTEMU
            return ip
        time.sleep(0.5)
    return "—"


def _ip_label(ip_value: str) -> str:
    """Zwraca tekst dla linii IP, z dopiskiem czasu uzyskania (od bootu)."""
    if ip_value == "—":
        return "— (waiting)" if SHOW_IP_DELAY else "—"
    if SHOW_IP_DELAY and _IP_FIRST_SEEN_AT is not None:
        dt = max(0.0, _IP_FIRST_SEEN_AT)  # to już jest uptime w sekundach
        return f"{ip_value} ({dt:.1f}s)"
    return ip_value


def gather_info(*, battery=None):
    # A late renderer supplies the exact already-assessed executor sample.
    # Standalone boot splash retains its bounded source wait and old layout.
    if isinstance(battery, dict) and battery.get("ready") is True and battery.get("value") is not None:
        batt = f"{battery['value'] * 100:.0f}"
    elif battery is not None:
        batt = "—"
    else:
        batt = pick_battery_nonblocking()
    batt_str = f"{batt}%" if batt.isdigit() else batt
    ip_raw = pick_ip_nonblocking()
    ip_str = _ip_label(ip_raw)
    info = {
        "Host": socket.gethostname(),
        "Date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "OS": read_os_pretty(),
        "Kernel": platform.release(),
        "Temp CPU": f"{read_temp_c()}°C",
        "Battery": batt_str,  # Battery PRZED IP
        "IP": ip_str,
    }
    if SPLASH_HIDE_EMPTY_BATT and batt_str == "—":
        info.pop("Battery", None)
    return info


# ---------------- RENDER ----------------
def draw_splash_with(info: dict, w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(img)

    title_font = load_font(28)
    body_font = load_font(24)
    small_font = load_font(16)
    big_font = load_font(28)

    margin = 14
    vspace = 10
    key_w = KEY_W
    text_w = w - margin * 2 - key_w

    title = "Rider-Pi — Device Info"
    d.text((margin, margin), title, fill=(255, 255, 255), font=title_font)
    y = margin + 40 + vspace

    _, body_h = text_size(d, "Ag", body_font)
    _, small_h = text_size(d, "Ag", small_font)
    _, big_h = text_size(d, "Ag", big_font)

    for k, v in info.items():
        if k == "Kernel":
            d.text((margin + key_w, y), v, fill=(180, 180, 180), font=small_font)
            y += small_h + 6 + LINE_EXTRA
            continue

        if k == "OS":
            d.text((margin, y), f"{k}:", fill=(180, 200, 255), font=body_font)
            lines = wrap_lines(d, v, body_font, text_w)
            for line in lines:
                d.text((margin + key_w, y), line, fill=(220, 220, 220), font=body_font)
                y += body_h + 4 + LINE_EXTRA
            continue

        if k == "IP":
            y += IP_SPACER
            d.text((margin, y), f"{k}:", fill=(200, 220, 255), font=big_font)
            d.text((margin + key_w, y), v, fill=(255, 255, 255), font=big_font)
            y += big_h + 8 + LINE_EXTRA
            continue

        d.text((margin, y), f"{k}:", fill=(180, 200, 255), font=body_font)
        d.text((margin + key_w, y), v, fill=(220, 220, 220), font=body_font)
        y += body_h + 8 + LINE_EXTRA

    return img


def maybe_rotate(im: Image.Image) -> Image.Image:
    if ROTATE in (90, 180, 270):
        return im.rotate(ROTATE, expand=True)
    return im


# ---------------- PRE-SLIDE (LOGO) WYŚWIETLANIE ----------------
def _load_logo_for_target(target_size: tuple[int, int]) -> Image.Image | None:
    """Ładuje logo, rotuje i dopasowuje (letterbox) do docelowego rozmiaru."""
    if SPLASH_LOGO_SECONDS <= 0:
        return None
    path = SPLASH_LOGO
    if not path or not os.path.isfile(path):
        return None
    try:
        im = Image.open(path).convert("RGB")
        im = maybe_rotate(im)
        im = _letterbox_fit(im, target_size)
        return im
    except Exception as e:
        _log(f"logo load failed: {e}")
        return None


# ---------------- WYŚWIETLANIE ----------------
def have_xgo() -> bool:
    try:
        import xgoscreen.LCD_2inch  # noqa: F401

        return True
    except Exception:
        return False


def _show_xgo_logo(sink, target_size):
    # PRE-SLIDE: logo
    logo_img = _load_logo_for_target(target_size)
    if logo_img is not None:
        try:
            sink.present_device(logo_img)
            _log(f"logo shown (xgo): {SPLASH_LOGO} for {SPLASH_LOGO_SECONDS:.1f}s")
            print(f"[splash] logo shown: {SPLASH_LOGO} ({SPLASH_LOGO_SECONDS:.1f}s)")
            time.sleep(SPLASH_LOGO_SECONDS)
        except Exception as e:
            _log(f"logo show failed (xgo): {e}")


def _present_xgo_info(sink, info, target_size):
    img = draw_splash_with(info, WIDTH, HEIGHT)
    img = maybe_rotate(img)
    if img.size != target_size:
        img = img.resize(target_size, Image.BICUBIC)
    sink.present_device(img)


def show_live_xgo():
    from apps.ui.lcd_sink import LcdSink

    sink = LcdSink()
    disp = getattr(sink.driver, "device", sink.driver)

    w = int(getattr(disp, "W", getattr(disp, "width", 240)))
    h = int(getattr(disp, "H", getattr(disp, "height", 320)))
    target_size = (w, h)

    try:
        _show_xgo_logo(sink, target_size)

        # tło
        sink.present_device(Image.new("RGB", target_size, (0, 0, 0)))

        t0 = time.time()
        last_payload = None
        first_frame = True

        while True:
            info = gather_info()
            if info != last_payload:
                _present_xgo_info(sink, info, target_size)
                last_payload = info
                if first_frame:
                    first_frame = False
                    if SPLASH_EARLY_EXIT == 1:
                        break

            if time.time() - t0 >= SECS:
                break
            time.sleep(REFRESH_EVERY)

        if CLEAR == 1:
            sink.present_device(Image.new("RGB", target_size, (0, 0, 0)))
        _log("xgo live display OK")
        return True
    finally:
        sink.release()


def have_pygame() -> bool:
    try:
        import pygame  # noqa: F401

        return True
    except Exception:
        return False


def _show_pygame_logo(pygame, screen, target_size):
    # PRE-SLIDE: logo
    logo_img = _load_logo_for_target(target_size)
    if logo_img is not None:
        try:
            surf = pygame.image.fromstring(logo_img.tobytes(), logo_img.size, logo_img.mode)
            screen.blit(surf, (0, 0))
            pygame.display.update()
            _log(f"logo shown (pygame): {SPLASH_LOGO} for {SPLASH_LOGO_SECONDS:.1f}s")
            print(f"[splash] logo shown: {SPLASH_LOGO} ({SPLASH_LOGO_SECONDS:.1f}s)")
            time.sleep(SPLASH_LOGO_SECONDS)
        except Exception as e:
            _log(f"logo show failed (pygame): {e}")


def show_live_pygame():
    import pygame

    os.environ.setdefault("SDL_VIDEODRIVER", "fbcon")
    if "FBDEV" in os.environ or os.path.exists(FBDEV):
        os.environ["SDL_FBDEV"] = os.environ.get("FBDEV", FBDEV)
    target_size = (HEIGHT, WIDTH) if ROTATE in (90, 270) else (WIDTH, HEIGHT)

    pygame.init()
    screen = pygame.display.set_mode(target_size, 0, 24)
    screen.fill((0, 0, 0))
    pygame.display.update()

    _show_pygame_logo(pygame, screen, target_size)

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
            screen.blit(surf, (0, 0))
            pygame.display.update()
            last_payload = info
            if SPLASH_EARLY_EXIT == 1:
                break
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
        if not ok and use in ("xgo", "auto") and have_xgo():
            ok = show_live_xgo()
        if not ok and use in ("pygame", "auto") and have_pygame():
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
