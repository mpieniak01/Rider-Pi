#!/usr/bin/env python3
#!/usr/bin/env python3
"""
Rider‑Pi — pogoda na 2" LCD (jednorazowy CLI): pobiera bieżącą pogodę z Open‑Meteo
(bez klucza), renderuje kartę 240×320 i wysyła na ekran przez legacy `_apps.ui.face_renderers`.

Naprawy/ulepszenia:
- Naprawiono błąd składni (niezamknięty cudzysłów) i wszystkie sekwencje końca linii ("\n").
- Usunięto `print(..., file=sys.stderr)` → `_eprint()` (`sys.stderr.write`).
- Dodano `--self-test` (testy offline renderera i pomiaru tekstu, bez sieci/LCD) + dodatkowe asercje.
- Fallback pomiaru tekstu (zgodność różnych wersji Pillow) i defensywne ścieżki.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.parse
import urllib.request
from typing import Any

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    sys.stderr.write("[weather] Brak Pillow (PIL). Zainstaluj: pip3 install pillow\n")
    raise

# --- Stałe UI ---
W, H = 240, 320
MARGIN = 10
FONT_SMALL: ImageFont.ImageFont | None = None
FONT_MED: ImageFont.ImageFont | None = None
FONT_BIG: ImageFont.ImageFont | None = None

# Kody pogody Open‑Meteo → opis i piktogram
WX: dict[int, tuple[str, str]] = {
    0: ("Bezchmurnie", "☀"),
    1: ("Przeważnie słońce", "🌤"),
    2: ("Częściowe zachm.", "⛅"),
    3: ("Pochmurno", "☁"),
    45: ("Mgła", "🌫"),
    48: ("Mgła oszron.", "🌫"),
    51: ("Mżawka lekka", "🌦"),
    53: ("Mżawka", "🌦"),
    55: ("Mżawka mocna", "🌧"),
    56: ("Marznąca mżawka", "🌧"),
    57: ("Marznąca mżawka", "🌧"),
    61: ("Deszcz lekki", "🌦"),
    63: ("Deszcz", "🌧"),
    65: ("Ulewa", "🌧"),
    66: ("Marznący deszcz", "🌧"),
    67: ("Marznący deszcz", "🌧"),
    71: ("Śnieg lekki", "🌨"),
    73: ("Śnieg", "🌨"),
    75: ("Śnieżyca", "❄"),
    77: ("Śnieg ziarnisty", "🌨"),
    80: ("Przelotne opady", "🌧"),
    81: ("Przel. opady", "🌧"),
    82: ("Ulewy", "🌧"),
    85: ("Przel. śnieg", "🌨"),
    86: ("Ulewy śniegu", "❄"),
    95: ("Burza", "⛈"),
    96: ("Burza z gradem", "⛈"),
    99: ("Burza z gradem", "⛈"),
}

# --- I/O pomocnicze ---


def _eprint(msg: str) -> None:
    sys.stderr.write(msg + "\n")


def _print(msg: str) -> None:
    sys.stdout.write(msg + "\n")


# --- HTTP ---


def http_get_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "RiderPi-Weather/1.0"})
    with urllib.request.urlopen(req, timeout=12) as r:
        data = r.read()
    return json.loads(data.decode("utf-8"))


def geocode_place(name: str) -> tuple[float, float, str]:
    qs = urllib.parse.urlencode(
        {
            "name": name,
            "count": 1,
            "language": "pl",
            "format": "json",
        }
    )
    url = f"https://geocoding-api.open-meteo.com/v1/search?{qs}"
    j = http_get_json(url)
    results = j.get("results") or []
    if not results:
        raise RuntimeError(f"Nie znaleziono lokalizacji: {name}")
    r0 = results[0]
    lat, lon = float(r0["latitude"]), float(r0["longitude"])
    label = f"{r0.get('name', '')} {r0.get('country_code', '')}".strip()
    return lat, lon, label


def fetch_weather(lat: float, lon: float, tz: str = "Europe/Warsaw") -> dict[str, Any]:
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": ",".join(
            [
                "temperature_2m",
                "relative_humidity_2m",
                "apparent_temperature",
                "precipitation",
                "weather_code",
                "wind_speed_10m",
                "wind_direction_10m",
            ]
        ),
        "daily": ",".join(
            [
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_sum",
            ]
        ),
        "timezone": tz,
        "forecast_days": 1,
        "language": "pl",
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    return http_get_json(url)


# --- Rysowanie ---


def load_fonts() -> None:
    global FONT_SMALL, FONT_MED, FONT_BIG
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ):
        try:
            FONT_SMALL = ImageFont.truetype(path, 16)
            FONT_MED = ImageFont.truetype(path, 22)
            FONT_BIG = ImageFont.truetype(path, 56)
            return
        except Exception:
            pass
    FONT_SMALL = ImageFont.load_default()
    FONT_MED = ImageFont.load_default()
    FONT_BIG = ImageFont.load_default()


def _measure(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    try:
        w = int(draw.textlength(text, font=font))
    except Exception:
        w = 0
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        h = bbox[3] - bbox[1]
        if w == 0:
            w = bbox[2] - bbox[0]
    except Exception:
        h = getattr(font, "size", 16)
        if w == 0:
            w = max(1, len(text) * max(6, h // 2))
    return w, h


def draw_label(
    draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font: ImageFont.ImageFont, fill=0
) -> tuple[int, int]:
    draw.text(xy, text, font=font, fill=fill)
    w, h = _measure(draw, text, font)
    return (xy[0] + w, xy[1] + h)


def render_card(data: dict[str, Any], place_label: str) -> Image.Image:
    img = Image.new("L", (W, H), color=255)
    draw = ImageDraw.Draw(img)

    now = dt.datetime.now()
    cur = data.get("current", {})
    daily = data.get("daily") or {}

    t = cur.get("temperature_2m")
    at = cur.get("apparent_temperature")
    rh = cur.get("relative_humidity_2m")
    ws = cur.get("wind_speed_10m")
    wd = cur.get("wind_direction_10m")
    pr = cur.get("precipitation")
    code = int(cur.get("weather_code") or 0)
    code_desc, code_icon = WX.get(code, (f"Kod {code}", "·"))

    tmin = (daily.get("temperature_2m_min") or [None])[0]
    tmax = (daily.get("temperature_2m_max") or [None])[0]
    pr_sum = (daily.get("precipitation_sum") or [None])[0]

    load_fonts()
    x, y = MARGIN, MARGIN
    draw.rounded_rectangle((0, 0, W - 1, H - 1), radius=16, outline=0, width=2)

    draw_label(draw, (x, y), place_label, FONT_MED)
    ts = now.strftime("%d %b, %H:%M")
    ts_w, ts_h = _measure(draw, ts, FONT_SMALL)
    draw_label(draw, (W - MARGIN - ts_w, y + 4), ts, FONT_SMALL)
    y += 40

    draw.text((x, y - 8), code_icon, font=FONT_BIG, fill=0)
    temp_text = f"{int(round(t)) if t is not None else '–'}°C"
    draw_label(draw, (x + 96, y + 4), temp_text, FONT_BIG)
    y += 78

    draw_label(draw, (x, y), code_desc, FONT_MED)
    y += 28

    line = []
    if at is not None:
        line.append(f"odcz. {int(round(at))}°C")
    if rh is not None:
        line.append(f"wilg. {int(round(rh))}%")
    if ws is not None:
        wds = f", {int(round(wd))}°" if wd is not None else ""
        line.append(f"wiatr {int(round(ws))} km/h{wds}")
    if pr is not None:
        line.append(f"opad {pr:.1f} mm")
    draw_label(draw, (x, y), "  •  ".join(line), FONT_SMALL)
    y += 24

    line2 = []
    if (tmin is not None) and (tmax is not None):
        line2.append(f"dziś {int(round(tmin))}/{int(round(tmax))}°C")
    if pr_sum is not None:
        line2.append(f"opad dziś {pr_sum:.1f} mm")
    draw_label(draw, (x, y), "  •  ".join(line2), FONT_SMALL)

    footer = "Dane: Open‑Meteo"
    fw, fh = _measure(draw, footer, FONT_SMALL)
    draw_label(draw, (W - MARGIN - fw, H - MARGIN - fh), footer, FONT_SMALL)

    return img


# --- LCD bridge ---


def push_to_lcd(img: Image.Image, rotate: int = 270, spi_hz: int | None = None) -> None:
    import importlib

    mod = importlib.import_module("_apps.ui.face_renderers")

    if rotate in (90, 180, 270):
        img = img.rotate(rotate, expand=True)
    if img.size != (240, 320):
        img = img.resize((240, 320), Image.BICUBIC)

    if spi_hz is not None:
        try:
            mod.SPI_HZ = int(spi_hz)
        except Exception:
            pass

    disp = None
    for attr in ("display", "Display", "lcd", "LCD"):
        disp = getattr(mod, attr, None)
        if disp:
            break

    try:
        if callable(disp):
            disp = disp()
    except Exception:
        pass

    try:
        if hasattr(disp, "Init"):
            disp.Init()
    except Exception:
        pass

    did = False
    for meth in ("ShowImage", "show", "draw", "DisplayImage", "blit"):
        if hasattr(disp, meth):
            try:
                getattr(disp, meth)(img)
                did = True
                break
            except Exception:
                pass

    if not did:
        for fn in ("ShowImage", "DisplayImage"):
            if hasattr(mod, fn):
                try:
                    getattr(mod, fn)(img)
                    did = True
                    break
                except Exception:
                    pass

    if not did:
        raise RuntimeError("Nie udało się wysłać obrazu na LCD (brak ShowImage)")


# --- CLI ---


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="weather_lcd", description='Pokaż bieżącą pogodę na LCD 2" (Rider‑Pi)')
    p.add_argument("--place", type=str, default="Warszawa", help="Miasto/miejscowość (geocoding)")
    p.add_argument("--lat", type=float, default=None, help="Szerokość geogr.")
    p.add_argument("--lon", type=float, default=None, help="Długość geogr.")
    p.add_argument("--rotate", type=int, default=270, choices=[0, 90, 180, 270], help="Rotacja LCD")
    p.add_argument("--spi-hz", type=int, default=None, help="Częstotliwość SPI")
    p.add_argument("--dry-run", action="store_true", help="Zapisz PNG do /tmp/weather.png zamiast LCD")
    p.add_argument("--self-test", action="store_true", help="Uruchom testy offline")
    return p.parse_args()


# --- Testy offline (bez sieci/LCD) ---


def _self_tests() -> int:
    # 1) Render z danymi przykładowymi
    mock = {
        "current": {
            "temperature_2m": 21.3,
            "apparent_temperature": 20.0,
            "relative_humidity_2m": 55,
            "precipitation": 0.0,
            "weather_code": 2,
            "wind_speed_10m": 14.2,
            "wind_direction_10m": 230,
        },
        "daily": {
            "temperature_2m_min": [12.1],
            "temperature_2m_max": [23.9],
            "precipitation_sum": [0.4],
        },
    }
    img = render_card(mock, "Test City PL")
    assert img.size == (W, H)

    # 2) Pomiar tekstu nie zwraca zer
    canvas = Image.new("L", (W, H), 255)
    drw = ImageDraw.Draw(canvas)
    load_fonts()
    w, h = _measure(drw, "ABC", FONT_SMALL)
    assert w > 0 and h > 0

    # 3) draw_label przesuwa kursor
    x2, y2 = draw_label(drw, (10, 10), "X", FONT_SMALL)
    assert (x2 > 10) and (y2 > 10)

    # 4) Nieznany kod pogody używa fallbacku
    mock2 = {"current": {"weather_code": 999}, "daily": {}}
    img2 = render_card(mock2, "X")
    assert img2.size == (W, H)

    # 5) Zapis PNG w trybie offline
    out = "/tmp/weather.png"
    img.convert("RGB").save(out, "PNG")

    return 0


def main() -> int:
    args = parse_args()

    if args.self_test:
        try:
            rc = _self_tests()
            _print("[weather] self-test OK")
            return rc
        except AssertionError as e:
            _eprint(f"[weather] self-test FAIL: {e}")
            return 10
        except Exception as e:
            _eprint(f"[weather] self-test ERROR: {e}")
            return 11

    try:
        if (args.lat is not None) and (args.lon is not None):
            lat, lon, label = args.lat, args.lon, f"{args.lat:.3f},{args.lon:.3f}"
        else:
            lat, lon, label = geocode_place(args.place)
    except Exception as e:
        _eprint(f"[weather] Geocoding nie powiódł się: {e}")
        return 2

    try:
        data = fetch_weather(lat, lon, tz="Europe/Warsaw")
    except Exception as e:
        _eprint(f"[weather] Pobranie pogody nie powiodło się: {e}")
        return 3

    try:
        img = render_card(data, place_label=label)
    except Exception as e:
        _eprint(f"[weather] Render nie powiódł się: {e}")
        return 4

    if args.dry_run:
        out = "weather.png"
        try:
            img.convert("RGB").save(out, "PNG")
            _print(f"[weather] Zapisano {out}")
            return 0
        except Exception as e:
            _eprint(f"[weather] Zapis PNG nie powiódł się: {e}")
            return 6

    try:
        push_to_lcd(img, rotate=args.rotate, spi_hz=args.spi_hz)
    except Exception as e:
        _eprint(f"[weather] Błąd wyświetlania na LCD: {e}")
        out = "/tmp/weather.png"
        try:
            img.convert("RGB").save(out, "PNG")
            _print(f"[weather] (awaryjnie) zapisano {out}")
        except Exception:
            pass
        return 5

    _print(f"[weather] OK — {label} ({lat:.3f},{lon:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
