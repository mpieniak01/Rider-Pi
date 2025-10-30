#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import glob
import os
import platform
import re
import socket
import subprocess
import sys
import time
from collections.abc import Iterable
from contextlib import contextmanager

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

OUT_IMG = os.path.join(DATA_DIR, "splash_device_info.png")
WIDTH = int(os.getenv("SPLASH_W", "480"))
HEIGHT = int(os.getenv("SPLASH_H", "320"))
ROTATE = int(os.getenv("SPLASH_ROTATE", os.getenv("PREVIEW_ROT", "0")) or 0)
SECS = float(os.getenv("SPLASH_SECONDS", "8"))
USE = os.getenv("SPLASH_USE", "auto")  # xgo|pygame|auto
CLEAR = int(os.getenv("SPLASH_CLEAR", "1"))
FBDEV = os.getenv("FBDEV", "/dev/fb1" if os.path.exists("/dev/fb1") else "/dev/fb0")

# --- PRE-SLIDE (LOGO) ---
SPLASH_LOGO = os.getenv("SPLASH_LOGO", os.path.join(DATA_DIR, "splash_logo.png"))
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
XGO_BL_GPIO = int(os.getenv("XGO_BL_GPIO", "-1"))
RASPI_GPIO_BIN = "raspi-gpio"

# Wygładzanie odczytów baterii
BATT_CACHE_SEC = float(os.getenv("BATT_CACHE_SEC", "5"))

LOG = os.path.join(DATA_DIR, "splash_trace.log")

# Znaczniki czasu dla IP (pierwsze udane wykrycie)
_START_TS = time.time()  # (pozostaje — już nie używamy do IP)
_IP_FIRST_SEEN_AT: float | None = None  # teraz: sekundy OD STARTU SYSTEMU (uptime)

# Cache baterii (wartość, timestamp)
_last_batt: tuple[str | None, float] = (None, 0.0)


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
        text = re.sub(r"\s*\(", "\n(", text, count=1)
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
    cleaned = re.sub(r"\s*\([^)]*\)", "", text)
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


# ---- BATERIA: sysfs ➜ XGOClientRO (UART) ----
def _read_batt_sysfs_once() -> int | None:
    base = "/sys/class/power_supply"
    try:
        found = False
        for d in glob.glob(f"{base}/*"):
            found = True
            tpath = os.path.join(d, "type")
            if os.path.isfile(tpath):
                try:
                    t = open(tpath).read().strip().lower()
                    if t and t != "battery":
                        continue
                except Exception:
                    pass
            cap = os.path.join(d, "capacity")
            if os.path.isfile(cap):
                try:
                    v = int(float(open(cap).read().strip()))
                    if 0 <= v <= 100:
                        return v
                except Exception:
                    pass
            uevent = os.path.join(d, "uevent")
            if os.path.isfile(uevent):
                try:
                    for ln in open(uevent, encoding="utf-8", errors="ignore"):
                        if ln.startswith("POWER_SUPPLY_CAPACITY="):
                            v = int(float(ln.split("=", 1)[1].strip()))
                            if 0 <= v <= 100:
                                return v
                except Exception:
                    pass
            pairs: Iterable[tuple[str, str]] = (
                ("charge_now", "charge_full"),
                ("energy_now", "energy_full"),
            )
            for now_name, full_name in pairs:
                p_now = os.path.join(d, now_name)
                p_full = os.path.join(d, full_name)
                if os.path.isfile(p_now) and os.path.isfile(p_full):
                    try:
                        now = float(open(p_now).read().strip())
                        full = float(open(p_full).read().strip())
                        if full > 0:
                            return int(max(0.0, min(100.0, (now / full) * 100.0)))
                    except Exception:
                        pass
        if not found:
            _log("battery: no entries under /sys/class/power_supply")
        else:
            _log("battery: power_supply present but no capacity/uevent/ratio")
    except Exception as e:
        _log(f"battery sysfs error: {e}")
    return None


@contextmanager
def _serial_batt_lock():
    """
    Prosty lockfile, żeby unikać równoległego dostępu do UART.
    Jeśli lock zajęty — logujemy i pozwalamy funkcji kontynuować (zwróci None).
    """
    lock_path = "/run/lock/xgo_batt.lock"
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    f = open(lock_path, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    except BlockingIOError:
        _log("battery: lock held by another process; skipping this read")
        yield
    finally:
        try:
            fcntl.flock(f, fcntl.LOCK_UN)
        except Exception:
            pass
        f.close()


def _read_batt_xgo_uart_once() -> int | None:
    """
    Bezpośredni odczyt z XGO po UART (biblioteka producenta).
    Autodetekcja portu: ENV XGO_UART_PORTS="/dev/ttyAMA0,/dev/ttyS0,/dev/ttyUSB0"
    + skan ttyUSB*.
    Dynamicznie ładujemy scripts/dev_xgo-client.py.
    """
    # załaduj scripts/dev_xgo-client.py (ma myślnik w nazwie)
    try:
        from common.xgo_loader import load_xgo_client_ro

        XGOCls = load_xgo_client_ro(DIR)
    except Exception as e_dyn:
        _log(f"battery: loading dev_xgo-client.py failed: {e_dyn}")
        return None

    if XGOCls is None:
        return None

    env_ports = os.getenv("XGO_UART_PORTS", "/dev/ttyAMA0,/dev/ttyS0")
    candidates = [p for p in (x.strip() for x in env_ports.split(",")) if p]
    try:
        candidates += sorted(glob.glob("/dev/ttyUSB*"))
    except Exception:
        pass

    tried: list[str] = []

    # ochrona portu lockiem
    with _serial_batt_lock():
        for port in candidates:
            tried.append(port)
            # drobny backoff 2 próby, bo czasem pierwszy odczyt po openie zwraca pustkę
            for _attempt in range(2):
                try:
                    with XGOCls(port=port) as cli:
                        if hasattr(cli, "read_battery_pct"):
                            v = cli.read_battery_pct()
                            if v is not None:
                                vv = int(v)
                                _log(f"battery: XGO UART {port} -> {vv}%")
                                return vv
                        v2 = cli.read_battery() if hasattr(cli, "read_battery") else None
                        if v2 is not None:
                            vv = int(v2)
                            _log(f"battery: XGO UART {port} -> {vv}%")
                            return vv
                except Exception as e:
                    _log(f"battery: XGO UART read failed on {port}: {e}")
                    time.sleep(0.12)  # krótki backoff i jeszcze raz
                    continue

    _log(f"battery: no working UART among: {', '.join(tried) if tried else '(none)'}")
    return None


def read_battery_once() -> str | None:
    for getter in (_read_batt_sysfs_once, _read_batt_xgo_uart_once):
        v = getter()
        if isinstance(v, int):
            _log(f"battery source: {getter.__name__} -> {v}%")
            return str(v)
    return None


def pick_battery_nonblocking() -> str:
    """
    Zwraca świeży odczyt, a przy krótkich dropach portu — ostatnią dobrą wartość
    z cache (do BATT_CACHE_SEC). Po upływie WAIT_BATT i bez cache zwraca '—'.
    """
    global _last_batt
    t_end = time.time() + max(0, WAIT_BATT)

    while True:
        now = time.time()
        v = read_battery_once()
        if v is not None:
            _last_batt = (v, now)
            return v

        # brak świeżego odczytu — użyj cache, jeśli nieprzeterminowany
        last_v, last_ts = _last_batt
        if last_v is not None and (now - last_ts) <= BATT_CACHE_SEC:
            return last_v

        if now >= t_end:
            return "—"

        time.sleep(0.25)


def _get_ipv4() -> str | None:
    try:
        out = subprocess.check_output(
            ["ip", "-4", "route", "get", "1.1.1.1"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        m = re.search(r"\bsrc (\d+\.\d+\.\d+\.\d+)\b", out or "")
        if m and m.group(1) != "127.0.0.1":
            _log(f"IP via route: {m.group(1)}")
            return m.group(1)
    except Exception as e:
        _log(f"route-get fail: {e}")

    try:
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
    except Exception as e:
        _log(f"hostname -I fail: {e}")

    try:
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
    except Exception as e:
        _log(f"ip -brief fail: {e}")

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


def gather_info():
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


# ---------------- HW: podświetlenie (opcjonalnie) ----------------
def _bl_set(low: bool) -> None:
    if XGO_BL_GPIO < 0:
        return
    try:
        subprocess.check_call(
            [RASPI_GPIO_BIN, "set", str(XGO_BL_GPIO), "op", "dl" if low else "dh"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _log(f"BL GPIO{XGO_BL_GPIO}: {'LOW' if low else 'HIGH'}")
    except Exception as e:
        _log(f"BL ctrl fail: {e}")


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


def show_live_xgo():
    import xgoscreen.LCD_2inch as LCD_2inch

    _bl_set(low=True)

    disp = LCD_2inch.LCD_2inch()
    disp.Init()
    disp.clear()

    w = int(getattr(disp, "W", getattr(disp, "width", 240)))
    h = int(getattr(disp, "H", getattr(disp, "height", 320)))
    target_size = (w, h)

    # PRE-SLIDE: logo
    logo_img = _load_logo_for_target(target_size)
    if logo_img is not None:
        try:
            disp.ShowImage(logo_img)
            _log(f"logo shown (xgo): {SPLASH_LOGO} for {SPLASH_LOGO_SECONDS:.1f}s")
            print(f"[splash] logo shown: {SPLASH_LOGO} ({SPLASH_LOGO_SECONDS:.1f}s)")
            time.sleep(SPLASH_LOGO_SECONDS)
        except Exception as e:
            _log(f"logo show failed (xgo): {e}")

    # tło
    disp.ShowImage(Image.new("RGB", target_size, (0, 0, 0)))

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
                _bl_set(low=False)
                first_frame = False
                if SPLASH_EARLY_EXIT == 1:
                    break

        if time.time() - t0 >= SECS:
            break
        time.sleep(REFRESH_EVERY)

    if CLEAR == 1:
        disp.ShowImage(Image.new("RGB", target_size, (0, 0, 0)))
    _log("xgo live display OK")
    return True


def have_pygame() -> bool:
    try:
        import pygame  # noqa: F401

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
    screen.fill((0, 0, 0))
    pygame.display.update()

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
