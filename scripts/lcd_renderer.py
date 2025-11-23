#!/usr/bin/env python3
"""
scripts/lcd_renderer.py – prosty renderer statusów scenariuszy na LCD.

Wyświetla listę aktywnych scenariuszy oraz podstawowe informacje z
`/run/rider/feature_state.json`. Jeżeli LCD lub sterownik nie są dostępne,
skrypt wypisuje dane w logach i kontynuuje.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

FONT_PATH = os.getenv("LCD_RENDERER_FONT", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
WIDTH = int(os.getenv("LCD_RENDERER_WIDTH", "240"))
HEIGHT = int(os.getenv("LCD_RENDERER_HEIGHT", "320"))
REFRESH = float(os.getenv("LCD_RENDERER_REFRESH", "5.0"))
STATE_PATH = Path(os.getenv("FEATURE_STATE_PATH", "/run/rider/feature_state.json"))
BG_COLOR = (0, 0, 0)
TITLE_COLOR = (255, 255, 255)
TEXT_COLOR = (0, 255, 128)
WARN_COLOR = (255, 200, 0)


try:
    from apps.hw.sink_lcd import LcdNotAvailable, SinkLCD
except Exception:  # pragma: no cover - fallback bez LCD

    class SinkLCD:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise LcdNotAvailable("sink_lcd unavailable")

    class LcdNotAvailable(RuntimeError): ...


class LCDRenderer:
    def __init__(self) -> None:
        self.lcd: SinkLCD | None = None
        try:
            self.lcd = SinkLCD(width=WIDTH, height=HEIGHT)
            print("[lcd_renderer] LCD initialized", flush=True)
        except Exception as exc:
            self.lcd = None
            print(f"[lcd_renderer] LCD unavailable: {exc}", flush=True)

        try:
            self.font_title = ImageFont.truetype(FONT_PATH, 20)
            self.font_body = ImageFont.truetype(FONT_PATH, 16)
        except Exception:
            self.font_title = ImageFont.load_default()
            self.font_body = ImageFont.load_default()

    def _render_lines(self, lines: Iterable[tuple[str, tuple[int, int, int]]]) -> Image.Image:
        img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)
        y = 8
        for text, color in lines:
            draw.text((8, y), text, font=self.font_body, fill=color)
            y += self.font_body.size + 6
            if y > HEIGHT - 20:
                break
        return img

    def display(self, title: str, lines: list[str], warn: bool = False) -> None:
        if not self.lcd:
            print("[lcd_renderer]", title, " | ".join(lines))
            return
        draw_lines = [(title, TITLE_COLOR if not warn else WARN_COLOR)]
        draw_lines += [(line, TEXT_COLOR) for line in lines]
        img = self._render_lines(draw_lines)
        try:
            self.lcd.push_auto(img)
        except Exception as exc:
            print(f"[lcd_renderer] push_auto failed: {exc}", flush=True)


def load_state() -> dict:
    try:
        data = json.loads(STATE_PATH.read_text())
        if isinstance(data, dict):
            return data
    except FileNotFoundError:
        pass
    except Exception as exc:
        print(f"[lcd_renderer] state read error: {exc}", flush=True)
    return {}


def summarize_state(state: dict) -> tuple[str, list[str], bool]:
    active = state.get("active") or []
    if not isinstance(active, list):
        active = []
    features = state.get("features") or []
    lines: list[str] = []
    warn = False
    if not active:
        lines.append("S0 – tylko usługi bazowe")
    else:
        for name in active:
            entry = next((f for f in features if f.get("name") == name), {})
            title = entry.get("title") or entry.get("description") or name
            status = "OK"
            services = entry.get("services") or []
            missing = [svc for svc in services if not svc.get("active")]
            if missing:
                status = f"brak {len(missing)} usług"
                warn = True
            lines.append(f"{title}: {status}")
    ts = state.get("ts")
    if ts:
        lines.append(f"ts: {time.strftime('%H:%M:%S', time.localtime(ts))}")
    return ("Aktywne scenariusze" if active else "Stan 0", lines, warn)


def main() -> int:
    renderer = LCDRenderer()
    while True:
        state = load_state()
        title, lines, warn = summarize_state(state)
        renderer.display(title, lines, warn=warn)
        time.sleep(max(1.0, REFRESH))


if __name__ == "__main__":
    sys.exit(main())
