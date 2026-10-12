#!/usr/bin/env python3
"""Refresh the existing boot Device Info screen after executor startup.

Uses the original IP/battery splash layout and rotation, then yields the LCD
after the existing idle interval. Reads executor snapshots, never UART/SDK.
"""

from __future__ import annotations

import importlib.util
import json
import os
import signal
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

from apps.safety.state import read_status
from apps.ui.status_panel import StatusPanelLifecycle, battery_observation
from common.observations import source_time

REFRESH = float(os.getenv("LCD_RENDERER_REFRESH", "5.0"))
STATE_PATH = Path(os.getenv("FEATURE_STATE_PATH", "/run/rider-motion/feature_state.json"))
_splash = None


def existing_splash():
    """Load composition/data helpers only; never execute the splash main."""
    global _splash
    if _splash is None:
        path = Path(__file__).with_name("sys_splash-info.py")
        spec = importlib.util.spec_from_file_location("rider_existing_splash", path)
        if spec is None or spec.loader is None:
            raise RuntimeError("existing_splash_unavailable")
        _splash = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_splash)
        # Executor may not have produced the first battery yet. An unknown
        # sample is shown explicitly, then replaced on the regular next poll.
        _splash.WAIT_BATT = 0
        _splash.WAIT_IP = 0
    return _splash


class LCDRenderer:
    def __init__(self, *, driver_factory=None, owner_probe=None) -> None:
        # Existing driver path; imports/initialization occur only after owner
        # inventory permits this renderer, never at module import/idle polling.
        from apps.ui.lcd_sink import LcdSink

        self._owner = LcdSink(factory=driver_factory, probe=owner_probe)
        self.lcd = self._owner.driver
        self.splash = existing_splash()
        self.rotate = self._owner.rotate
        self.frame_observation = None
        self.frame_path = Path(os.getenv("LCD_RUNTIME_FRAME", "/run/rider-motion/splash_device_info.png"))

    def close(self):
        self._owner.release()

    @property
    def power_known(self):
        # Driver sets this only after GPIO.setup/output accepted without an
        # exception. BCM0 is a valid pin; never test its truthiness.
        return getattr(self.lcd, "_bl_pin", None) is not None

    def display(self, title: str, lines: list[str], warn: bool = False, *, frame=None) -> None:
        info = frame if isinstance(frame, dict) else self.splash.gather_info()
        img = self.splash.draw_splash_with(info, self.splash.WIDTH, self.splash.HEIGHT)
        img = self.splash.maybe_rotate(img)
        device = getattr(self.lcd, "device", self.lcd)
        target = (
            int(getattr(device, "W", getattr(device, "width", 240))),
            int(getattr(device, "H", getattr(device, "height", 320))),
        )
        if img.size != target:
            img = img.resize(target, Image.BICUBIC)
        try:
            self._owner.present_device(img)
        except Exception as exc:
            print(f"[lcd_renderer] present failed: {exc}", flush=True)
            raise
        # The tmpfs artifact proves the submitted pixels, not physical panel
        # visibility. Failure to save diagnostic pixels never repeats GPIO.
        temporary = None
        saved = False
        try:
            fd, temporary = tempfile.mkstemp(prefix=".lcd-frame-", suffix=".png", dir=self.frame_path.parent)
            os.close(fd)
            img.save(temporary)
            os.replace(temporary, self.frame_path)
            temporary = None
            saved = True
        except OSError as exc:
            print("[lcd_renderer] frame artifact unavailable:", type(exc).__name__, flush=True)
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
        self.frame_observation = {
            "layout": "existing_device_info",
            "ip": info.get("IP"),
            "battery_text": info.get("Battery"),
            "rot": self.rotate,
            "width": target[0],
            "height": target[1],
            "path": str(self.frame_path) if saved else None,
            "confirmation": "frame_write_accepted",
            "physical_validity": "unverified",
        }


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
        print("[lcd_renderer]", json.dumps(fields, ensure_ascii=True), flush=True)
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
            if not lifecycle.off_confirmed:
                battery = battery_observation(read_status(), now=time.time())
                info = existing_splash().gather_info(battery=battery)
                try:
                    # IP/battery/date updates are telemetry, not user activity;
                    # they do not postpone OFF or wake a finished startup display.
                    lifecycle.step({}, battery, "Rider-Pi — Device Info", [], frame=info)
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
