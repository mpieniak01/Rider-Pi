"""Find declared selected-profile modules without importing hardware/ML."""

from __future__ import annotations

import importlib.util

from common.service_catalog import UNIT_CATALOG


def missing(units: tuple[str, ...], options: dict) -> list[str]:
    modules = {module for unit in units for module in UNIT_CATALOG[unit].get("runtime_modules", [])}
    if "rider-voice-web.service" in units:
        domain = options.get("domain", "voice")
        if domain in {"asr", "voice"}:
            modules.add("vosk")
        if domain in {"tts", "voice"}:
            modules.add("piper")
    errors = []
    for module in sorted(modules):
        try:
            found = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            errors.append(module)
    return errors
