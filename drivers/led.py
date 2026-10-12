"""One sysfs LED backend; reading never changes trigger or brightness."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path


def root():
    return Path(os.getenv("RIDER_LED_SYSFS", "/sys/class/leds"))


def select(name=None):
    entries = {p.name: p for p in root().glob("*") if p.is_dir() and (p / "brightness").is_file()}
    chosen = name or os.getenv("LED_NAME")
    if chosen:
        if not isinstance(chosen, str) or not re.fullmatch(r"[\w:.-]{1,128}", chosen) or chosen in {".", ".."}:
            raise ValueError("invalid_led_name")
        matched = next((p for key, p in entries.items() if key.lower() == chosen.lower()), None)
        if matched is None:
            raise ValueError("led_unavailable")
        return matched
    for wanted in ("act", "led0", "pwr", "led1"):
        path = next((p for key, p in entries.items() if key.lower() == wanted), None)
        if path is not None:
            return path
    raise ValueError("led_unavailable")


def snapshot(name=None):
    try:
        path = select(name)
        brightness = int((path / "brightness").read_text().strip())
        triggers = (path / "trigger").read_text().split()
        active = next((v[1:-1] for v in triggers if v.startswith("[") and v.endswith("]")), None)
        return {
            "resource": "led",
            "name": path.name,
            "source": "sysfs",
            "observed_at": time.time(),
            "state": "on" if brightness else "off",
            "brightness": brightness,
            "trigger": active,
            "error": None,
            "physical_validity": "unverified",
        }
    except (OSError, ValueError) as exc:
        return {"resource": "led", "state": "unavailable", "observed_at": None, "source": "sysfs", "error": str(exc)}


def apply(body):
    action = body.get("action")
    if action not in {"on", "off", "auto", "blink"}:
        raise ValueError("unknown_led_action")
    path = select(body.get("name"))
    maximum = int((path / "max_brightness").read_text().strip())
    if action == "blink":
        on, off = body.get("on_ms", 500), body.get("off_ms", 500)
        if any(type(v) is not int or not 1 <= v <= 60000 for v in (on, off)):
            raise ValueError("invalid_led_blink_period")
        (path / "trigger").write_text("timer")
        (path / "delay_on").write_text(str(on))
        (path / "delay_off").write_text(str(off))
        (path / "brightness").write_text(str(maximum))
    elif action == "auto":
        # Choose only an existing kernel default; never guess a hardware trigger.
        trigger = path / "device/of_node/linux,default-trigger"
        value = trigger.read_bytes().rstrip(b"\0").decode() if trigger.exists() else body.get("default_trigger")
        available = {
            (v[1:-1] if v.startswith("[") and v.endswith("]") else v) for v in (path / "trigger").read_text().split()
        }
        if not isinstance(value, str) or value not in available:
            raise ValueError("led_default_trigger_unavailable")
        (path / "trigger").write_text(value)
    else:
        (path / "trigger").write_text("none")
        (path / "brightness").write_text(str(maximum if action == "on" else 0))
    return {"ok": True, "confirmation": "control_write_accepted", "led": snapshot(path.name)}
