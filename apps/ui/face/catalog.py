"""One gesture library and runtime settings, stored locally on the serving Pi."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import random
import tempfile
import threading
import uuid
from pathlib import Path

from .characters import SKINS
from .gestures import blink, look
from .renderer import STYLES
from .schema import (
    CONTRACT,
    EASING,
    FIELDS,
    MAX_AUTHORED_DURATION_S,
    MAX_PLAYBACK_DURATION_S,
    MOODS,
    VERSION,
    number,
    validate,
)

ROOT = Path(__file__).resolve().parents[3]
LOCK = threading.RLock()
MAX_BYTES = 1024 * 1024


def library_path():
    return Path(os.getenv("FACE_STUDIO_LIBRARY", str(ROOT / "config/local/face-studio.json")))


def settings_path():
    return Path(os.getenv("FACE_RUNTIME_SETTINGS", str(ROOT / "config/local/face-runtime.json")))


def read_json(path):
    if not path.exists():
        return {}
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("face_file_too_large")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("invalid_library")
    return data


def atomic_write(path, data):
    encoded = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
    if len(encoded.encode("utf-8")) > MAX_BYTES:
        raise ValueError("face_file_too_large")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".face-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def builtin_items():
    items = [
        {"id": "builtin:blink", "builtin": True, **validate(blink())},
        {"id": "builtin:look", "builtin": True, **validate(look(rng=random.Random(0)))},
    ]
    for name, values in MOODS.items():
        initial = dict.fromkeys(FIELDS, 0.0)
        initial.update(values)
        items.append(
            {
                "id": "builtin:" + name,
                "builtin": True,
                **validate({"name": name, "expr": name, "duration": 1, "initial": initial}),
            }
        )
    return items


class Catalog:
    def __init__(self):
        self._stamp = None
        self._items = []
        self.revision = 0

    def items(self):
        with LOCK:
            path = library_path()
            stat = path.stat() if path.exists() else None
            stamp = (str(path), stat.st_mtime_ns if stat else None, stat.st_size if stat else None)
            if stamp != self._stamp:
                data = read_json(path)
                if len(data) > 200:
                    raise ValueError("invalid_library")
                self._items = builtin_items() + [
                    {"id": key, "builtin": False, **validate(spec)} for key, spec in data.items()
                ]
                self._stamp, self.revision = stamp, self.revision + 1
            return copy.deepcopy(self._items)

    def get(self, key):
        return next(
            (item for item in self.items() if item["id"] == key or item["builtin"] and item["name"] == key), None
        )

    def save(self, body):
        with LOCK:
            spec = validate(body)
            data = read_json(library_path())
            key = body.get("id")
            if key is not None and (not isinstance(key, str) or key not in data):
                raise ValueError("unknown_gesture")
            if key is None and len(data) >= 200:
                raise ValueError("library_full")
            key = key or uuid.uuid4().hex
            data[key] = spec
            atomic_write(library_path(), data)
            return key, spec

    def delete(self, key):
        with LOCK:
            data = read_json(library_path())
            if key not in data:
                return False
            settings = get_settings()
            if key in settings["active_gestures"]:
                settings["active_gestures"] = [item for item in settings["active_gestures"] if item != key]
                atomic_write(settings_path(), settings)
            del data[key]
            atomic_write(library_path(), data)
            return True


CATALOG = Catalog()


def get_settings():
    defaults = {
        "style": "friendly",
        "skin": "none",
        "power_mode": "battery",
        "idle": True,
        "intensity": 1.0,
        "tempo": 1.0,
        "transition": "original",
        "active_gestures": [item["id"] for item in builtin_items()],
    }
    data = read_json(settings_path())
    if set(data) - set(defaults):
        raise ValueError("unknown_face_setting")
    return _validate_settings({**defaults, **data})


def settings_revision(settings=None):
    data = get_settings() if settings is None else settings
    return hashlib.sha256(json.dumps(data, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _validate_settings(settings):
    if settings["style"] not in STYLES or settings["power_mode"] not in {"battery", "cable"}:
        raise ValueError("invalid_face_settings")
    if settings["skin"] not in SKINS:
        raise ValueError("invalid_face_skin")
    if type(settings["idle"]) is not bool:
        raise ValueError("invalid_face_settings")
    settings["intensity"] = number(settings["intensity"], 0, 1)
    settings["tempo"] = number(settings["tempo"], 0.5, 2)
    if settings["transition"] not in EASING | {"original"}:
        raise ValueError("invalid_transition")
    active = settings["active_gestures"]
    available = {item["id"] for item in CATALOG.items()}
    if (
        not isinstance(active, list)
        or len(active) > 209
        or any(not isinstance(key, str) or key not in available for key in active)
    ):
        raise ValueError("unknown_gesture")
    settings["active_gestures"] = list(dict.fromkeys(active))
    return settings


def save_settings(body, expected_revision=None):
    with LOCK:
        if not isinstance(body, dict):
            raise ValueError("invalid_face_settings")
        settings = get_settings()
        if expected_revision is not None and expected_revision != settings_revision(settings):
            raise ValueError("face_settings_conflict")
        if set(body) - set(settings):
            raise ValueError("unknown_face_setting")
        settings.update(body)
        _validate_settings(settings)
        atomic_write(settings_path(), settings)
        return settings


def descriptors():
    return {
        "contract_id": CONTRACT,
        "contract_version": VERSION,
        "fields": FIELDS,
        "styles": [
            {"id": "friendly", "pl": "Przyjazna", "en": "Friendly"},
            {"id": "minimal", "pl": "Prosta", "en": "Simple"},
            {"id": "legacy", "pl": "Dotychczasowa", "en": "Original"},
        ],
        "skins": [{"id": key, "pl": value["pl"], "en": value["en"]} for key, value in SKINS.items()],
        "expressions": list(MOODS),
        "intensity": {"min": 0, "max": 100, "step": 1, "unit": "%"},
        "tempo": {"min": 50, "max": 200, "step": 5, "unit": "%"},
        "duration": {"min": 50, "max": MAX_AUTHORED_DURATION_S * 1000, "step": 10, "unit": "ms"},
        "playback_duration_max_ms": MAX_PLAYBACK_DURATION_S * 1000,
        "fps": {"battery": 6, "cable": 12, "preview": 12},
        "idle_off_after_s": 45,
        "transitions": ["original", "lin", "in_out", "in", "out"],
        "expression_defaults": MOODS,
    }
