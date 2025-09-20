from __future__ import annotations
"""
Nowe CLI do renderowania buźki na LCD/mocka.
"""

import argparse
import os
import sys

from PIL import Image, ImageDraw

from apps.ui.face.driver import make_driver
from apps.ui.face.face_io import apply_rotate, fit_strategy, to_rgb565
from apps.ui.face.panel_cfg import PanelCfg

# Przykładowe ekspresje (neutral, happy, sad, blink...)
EXPR_MAP = {
    "neutral": (200, 200, 200),
    "happy": (255, 255, 0),
    "sad": (0, 128, 255),
    "blink": (50, 50, 50),
}

PANEL_SIZE = (240, 240)


def make_expr_img(expr: str) -> Image.Image:
    color = EXPR_MAP.get(expr, (128, 128, 128))
    img = Image.new("RGB", PANEL_SIZE, color)
    d = ImageDraw.Draw(img)
    d.text((10, 10), expr, fill=(0, 0, 0))
    return img


def parse_env_or_arg(val, env, default, typ=str):
    if val is not None:
        return typ(val)
    if env in os.environ:
        return typ(os.environ[env])
    return default


def main():
    parser = argparse.ArgumentParser(description="Face LCD CLI (mock/spi)")
    parser.add_argument("--expr", default="neutral", help="Ekspresja: neutral, happy, sad, blink...")
    parser.add_argument("--rotate", type=int, choices=[0, 90, 180, 270], help="Rotacja LCD (0/90/180/270)")
    parser.add_argument("--spi-hz", type=int, help="Częstotliwość SPI (opcjonalnie)")
    parser.add_argument("--fit", choices=["fill", "fit", "stretch"], help="Tryb dopasowania obrazu")
    parser.add_argument(
        "--force",
        choices=["raw:rgb565", "push_frame:rgb565_3", "png"],
        default="raw:rgb565",
        help="Tryb wypychania klatki",
    )
    parser.add_argument("--backend", choices=["mock", "spi"], help="Backend drivera (domyślnie mock lub z ENV)")
    parser.add_argument("--stats", action="store_true", help="Wyświetl info o plikach mocka")
    args = parser.parse_args()

    # Pobierz ustawienia z ENV lub argumentów
    rotate = parse_env_or_arg(args.rotate, "FACE_LCD_ROTATE", 0, int)
    fit = parse_env_or_arg(args.fit, "FACE_LCD_FIT", "fill", str)
    backend = parse_env_or_arg(args.backend, "FACE_LCD_BACKEND", "mock", str)
    parse_env_or_arg(args.spi_hz, "FACE_LCD_SPI_HZ", None, int)

    cfg = PanelCfg(rotate=rotate, fit=fit)
    driver = make_driver(backend, cfg)

    img = make_expr_img(args.expr)
    img = fit_strategy(img, fit, PANEL_SIZE)
    img = apply_rotate(img, rotate)

    if args.force == "raw:rgb565":
        buf = to_rgb565(img)
        driver.push_rgb565(buf, *PANEL_SIZE)
    elif args.force == "push_frame:rgb565_3":
        # Fallback: identycznie jak raw, ale można dodać inne ścieżki
        buf = to_rgb565(img)
        driver.push_rgb565(buf, *PANEL_SIZE)
    elif args.force == "png":
        driver.push_png(img)
    else:
        print(f"Nieznany tryb --force: {args.force}", file=sys.stderr)
        sys.exit(1)

    if args.stats:
        base = "/tmp/face_last"
        for ext in [".png", ".rgb565", ".meta.json"]:
            p = base + ext
            if os.path.exists(p):
                print(f"{p}: {os.path.getsize(p)} B")
        if os.path.exists(base + ".meta.json"):
            import json

            with open(base + ".meta.json") as f:
                print(json.dumps(json.load(f), indent=2))


if __name__ == "__main__":
    main()
