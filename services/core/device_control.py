"""Server-independent device operations, shared by API and emergency CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from common.secure_files import atomic_write


def _led_sessions():
    path = Path(os.getenv("RIDER_LED_STATE_PATH", "/run/rider-motion/led_state.json"))
    try:
        if path.stat().st_size > 65536:
            return path, {}
        data = json.loads(path.read_text())
        from services.core.goal_journal import boot_id

        sessions = data.get("sessions", {}) if data.get("boot_id") == boot_id() else {}
        return path, sessions if isinstance(sessions, dict) else {}
    except (OSError, ValueError, AttributeError):
        return path, {}


def _led_defaults():
    from services.core.goal_journal import boot_id

    path, _ = _led_sessions()
    try:
        data = json.loads(path.read_text())
        values = data.get("defaults", {}) if data.get("boot_id") == boot_id() else {}
        return values if isinstance(values, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def _save_led_generation(name, previous_trigger=None):
    from services.core.goal_journal import boot_id

    path, sessions = _led_sessions()
    defaults = _led_defaults()
    if isinstance(previous_trigger, str) and previous_trigger:
        defaults.setdefault(name, previous_trigger)
    generation = uuid.uuid4().hex
    sessions[name] = generation
    data = json.dumps({"boot_id": boot_id(), "sessions": sessions, "defaults": defaults}).encode("utf-8")
    atomic_write(path, lambda stream: stream.write(data))
    return generation


def led_status(name=None):
    from drivers.led import root, snapshot

    data = snapshot(name)
    data["available_leds"] = sorted(p.name for p in root().glob("*") if p.is_dir() and (p / "brightness").is_file())
    data["generation"] = _led_sessions()[1].get(data.get("name"))
    return data


def led_action(body):
    from drivers.led import select, snapshot

    try:
        path = select(body.get("name"))
    except ValueError as error:
        return {"ok": False, "error": str(error)}, 409
    expected = body.get("if_generation")
    if expected is not None and expected != _led_sessions()[1].get(path.name):
        return {"ok": False, "error": "led_session_changed"}, 409
    previous_trigger = snapshot(path.name).get("trigger")
    command = Path(__file__).resolve().parents[2] / "scripts/led-backend.py"
    prefix = [] if os.geteuid() == 0 else ["sudo", "-n"]
    try:
        result = subprocess.run(
            [
                *prefix,
                sys.executable,
                str(command),
                json.dumps({**body, "name": path.name, "default_trigger": _led_defaults().get(path.name)}),
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        data = json.loads(result.stdout)
        if not isinstance(data, dict):
            raise ValueError("invalid_led_backend_response")
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        return {"ok": False, "error": "led_action_unconfirmed", "detail": str(error)}, 503
    if result.returncode or data.get("ok") is not True:
        return {"ok": False, "error": data.get("error", "led_action_unconfirmed")}, 503
    try:
        data["generation"] = _save_led_generation(path.name, previous_trigger)
    except OSError as error:
        return {**data, "ok": False, "error": "led_journal_unavailable", "detail": str(error)}, 503
    data["name"] = path.name
    return data, 200


def lcd_action(manager, body, *, face_runtime=None):
    action = body.get("action")
    if action == "on":
        state = face_runtime.get_state()["state"] if face_runtime else {}
        if state.get("running") and state.get("sink") == "lcd":
            return {"ok": True, "idempotent": True, "face": state}, 200
        result = manager.service_action("lcd-renderer.service", "restart")
    elif action == "off":
        if face_runtime:
            stopped = face_runtime.stop()
            if stopped["state"].get("playing") or stopped["state"].get("running"):
                return stopped, stopped.get("status", 409)
        result = manager.service_action("lcd-renderer.service", "stop")
    else:
        return {"ok": False, "error": "unknown_lcd_action"}, 400
    return result, 200 if result.get("ok") else result.get("http_status", 409)


def action(manager, name, body, *, face_runtime=None):
    with manager.transaction():
        if name == "lcd":
            return lcd_action(manager, body, face_runtime=face_runtime)
        if name == "led":
            return led_action(body)
    return {"ok": False, "error": "unsupported_device"}, 404
