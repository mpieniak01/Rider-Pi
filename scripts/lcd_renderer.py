#!/usr/bin/env python3
"""
scripts/lcd_renderer.py – prosty renderer statusów scenariuszy na LCD.

Wyświetla listę aktywnych scenariuszy oraz podstawowe informacje z
`/run/rider-motion/feature_state.json`. Jeżeli LCD lub sterownik nie są dostępne,
skrypt wypisuje dane w logach i kontynuuje.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

from apps.safety.state import read_status
from apps.ui.status_panel import StatusPanelLifecycle, battery_observation
from common.observations import source_time

FONT_PATH = os.getenv("LCD_RENDERER_FONT", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
WIDTH = int(os.getenv("LCD_RENDERER_WIDTH", "240"))
HEIGHT = int(os.getenv("LCD_RENDERER_HEIGHT", "320"))
REFRESH = float(os.getenv("LCD_RENDERER_REFRESH", "5.0"))
STATE_PATH = Path(os.getenv("FEATURE_STATE_PATH", "/run/rider-motion/feature_state.json"))
BG_COLOR = (0, 0, 0)
TITLE_COLOR = (255, 255, 255)
TEXT_COLOR = (0, 255, 128)
WARN_COLOR = (255, 200, 0)


class LCDRenderer:
    def __init__(self, *, driver_factory=None) -> None:
        # Existing driver path; imports/initialization occur only after owner
        # inventory permits this renderer, never at module import/idle polling.
        if driver_factory is None:
            from drivers.lcd.driver_ili9xx import FaceConfig, LCDRenderer as Driver

            def driver_factory():
                return Driver(FaceConfig(lcd_bl_pin=0))

        self.lcd = driver_factory()
        self.rotate = int(os.getenv("FACE_LCD_ROTATE", "270"))
        try:
            self.font_title = ImageFont.truetype(FONT_PATH, 20)
            self.font_body = ImageFont.truetype(FONT_PATH, 16)
        except Exception:
            self.font_title = ImageFont.load_default()
            self.font_body = ImageFont.load_default()

    def close(self):
        # Do not call driver.cleanup(): it also writes shared GPIO. The power
        # operation is separate and needs a new no-external-owner inventory.
        device = getattr(self.lcd, "device", None)
        spi = getattr(device, "SPI", None)
        if spi is not None and callable(getattr(spi, "close", None)):
            spi.close()
        # The legacy driver may also own a module-local raw SPI descriptor.
        # Close only that descriptor; its cleanup() would toggle shared GPIO.
        driver_module = sys.modules.get(type(self.lcd).__module__)
        raw_state = getattr(driver_module, "_RAWSPI", None)
        raw_spi = raw_state.get("spi") if isinstance(raw_state, dict) else None
        if raw_spi is not None and raw_spi is not spi and callable(getattr(raw_spi, "close", None)):
            raw_spi.close()
            raw_state.update(spi=None, inited=False)

    @property
    def power_known(self):
        # Driver sets this only after GPIO.setup/output accepted without an
        # exception. BCM0 is a valid pin; never test its truthiness.
        return getattr(self.lcd, "_bl_pin", None) is not None

    def _render_lines(self, lines: Iterable[tuple[str, tuple[int, int, int]]]) -> Image.Image:
        img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)
        y = 8
        for text, color in lines:
            draw.text((8, y), text, font=self.font_body, fill=color)
            y += getattr(self.font_body, "size", 16) + 6
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
            self.lcd.ShowImage(img.rotate(self.rotate, expand=True) if self.rotate else img)
        except Exception as exc:
            print(f"[lcd_renderer] present failed: {exc}", flush=True)
            raise


def load_state() -> dict:
    try:
        if STATE_PATH.stat().st_size > 131072:
            raise ValueError("feature_state_too_large")
        data = json.loads(STATE_PATH.read_text())
        if isinstance(data, dict):
            return data
    except FileNotFoundError:
        # State file doesn't exist yet; return empty dict
        pass
    except Exception as exc:
        print(f"[lcd_renderer] state read error: {exc}", flush=True)
    return {}


def summarize_state(state: dict) -> tuple[str, list[str], bool]:
    state = state if isinstance(state, dict) else {}
    active = state.get("active") or []
    if not isinstance(active, list):
        active = []
    features = state.get("features") or []
    features = [row for row in features if isinstance(row, dict)] if isinstance(features, list) else []
    lines: list[str] = []
    warn = False
    if not active:
        lines.append("S0 – tylko usługi bazowe")
    else:
        for name in active:
            entry = next((f for f in features if f.get("name") == name), {})
            title = entry.get("title") or entry.get("description") or name
            status = "ostatni zapis: " + str(entry.get("state", "unknown"))
            services = entry.get("services") or []
            services = [row for row in services if isinstance(row, dict)] if isinstance(services, list) else []
            missing = [svc for svc in services if not svc.get("active")]
            if missing:
                status = f"brak {len(missing)} usług"
                warn = True
            lines.append(f"{title}: {status}")
    ts = source_time(state.get("ts"))
    if ts is not None:
        try:
            lines.append(f"ts: {time.strftime('%H:%M:%S', time.localtime(ts))}")
        except (OverflowError, OSError, ValueError):
            pass
    return ("Zadania (ostatni zapis)" if active else "Stan 0", lines, warn)


def power_off() -> bool:
    from apps.ui.lcd_power import off_if_free

    return off_if_free()["ok"]


def main() -> int:
    from services.api_core import resource_diag

    publisher = None
    running = True

    def report(**fields):
        nonlocal publisher
        print("[lcd_renderer]", fields["reason"], "on=", fields["on"], flush=True)
        try:
            if publisher is None:
                from common.bus import BusPub

                publisher = BusPub()
            publisher.publish(
                "ui.lcd.state",
                {
                    "source": "lcd-renderer",
                    "observed_at": time.time(),
                    "lcd": {**fields, "physical_validity": "unverified", "confirmation": "control_write_accepted"},
                },
                add_ts=False,
            )
        except Exception as exc:
            print("[lcd_renderer] status publish failed:", type(exc).__name__, flush=True)

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    lifecycle = StatusPanelLifecycle(
        sink_factory=LCDRenderer,
        owner_probe=lambda: resource_diag.inspect("lcd"),
        power_off=power_off,
        report=report,
        idle_s=float(os.getenv("LCD_IDLE_OFF_AFTER_S", "45")),
    )
    try:
        while running:
            state = load_state()
            title, lines, warn = summarize_state(state)
            battery = battery_observation(read_status(), now=time.time())
            try:
                lifecycle.step(state, battery, title, lines, warn)
            except Exception as exc:
                print("[lcd_renderer] render failed:", type(exc).__name__, flush=True)
            time.sleep(max(1.0, REFRESH))
    finally:
        lifecycle.close()
        if publisher is not None:
            publisher.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
