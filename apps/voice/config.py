"""Configuration loader for the voice stack.

Configuration precedence:
1. Internal defaults defined in :data:`DEFAULT_CONFIG`.
2. YAML file loaded from ``configs/voice.yaml`` (if present) or a path
   passed via ``--config``.
3. Environment variables (prefixed with ``VOICE_``).
4. CLI overrides passed as dictionaries (typically created by
   ``apps.voice.cli`` helpers).

The loader returns a deeply merged dictionary.  The rest of the codebase
uses plain dictionaries to keep the surface area small; dataclasses would
introduce copies when merging nested settings.  Helper functions are
provided to extract typed values with defaults.
"""
from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG: dict[str, Any] = {
    "capture": {
        "backend": "pulse",  # pulse|alsa|command
        "device": None,
        "sample_rate": 16_000,
        "channels": 1,
        "frame_ms": 30,
        "buffer_seconds": 5,
        "command": None,
    },
    "vad": {
        "enabled": True,
        "mode": 3,
        "frame_ms": 30,
        "tail_ms": 350,
        "max_len_ms": 4500,
        "energy_gate_dbfs": -36.0,
    },
    "hotword": {
        "enabled": True,
        "engine": "nyumaya",  # nyumaya|porcupine|ptt|off
        "model": None,
        "sensitivity": 0.6,
        "auto_gain": 1.0,
        "threshold": 0.6,
    },
    "asr": {
        "backend": "openai",  # openai|vosk|faster-whisper|whispercpp
        "model": "gpt-4o-mini-transcribe",
        "language": "en",
        "temperature": 0.0,
        "prompt": None,
        "vosk_model_dir": "models/vosk",
        "whisper_model": "medium",
        "input_encoding": "s16le",
    },
    "nlu": {
        "chat_threshold": 0.35,
        "command_keywords": {
            "stop": ["stop", "stój", "zatrzymaj"],
            "forward": ["go forward", "naprzód"],
            "back": ["go back", "wstecz"],
            "left": ["turn left", "w lewo"],
            "right": ["turn right", "w prawo"],
        },
        "llm_model": "gpt-4o-mini",
    },
    "chat": {
        "backend": "openai",
        "model": "gpt-4o-mini",
        "system_prompt": "You are Rider-Pi, a friendly voice assistant.",
        "max_history": 4,
    },
    "tts": {
        "backend": "openai",  # openai|piper
        "model": "gpt-4o-mini-tts",
        "voice": "alloy",
        "format": "wav",
        "piper_model": None,
        "piper_config": None,
    },
    "playback": {
        "backend": "pulse",  # pulse|alsa|auto
        "alsa_device": "default",
        "volume": 100,
        "ding": {
            "enabled": True,
            "path": "assets/sounds/ding.wav",
            "gain_db": 0.0,
        },
    },
    "service": {
        "save_audio": False,
        "recordings_dir": "data/recordings",
        "history_size": 20,
    },
    "web": {
        "host": "127.0.0.1",
        "port": 8092,
        "allow_origins": ["*"],
    },
    "logging": {
        "level": "INFO",
    },
}

ENV_MAPPING: dict[str, tuple[str, ...]] = {
    "VOICE_CAPTURE_BACKEND": ("capture", "backend"),
    "VOICE_CAPTURE_DEVICE": ("capture", "device"),
    "VOICE_CAPTURE_COMMAND": ("capture", "command"),
    "VOICE_ASR_BACKEND": ("asr", "backend"),
    "VOICE_ASR_MODEL": ("asr", "model"),
    "VOICE_ASR_LANG": ("asr", "language"),
    "VOICE_TTS_BACKEND": ("tts", "backend"),
    "VOICE_TTS_VOICE": ("tts", "voice"),
    "VOICE_TTS_MODEL": ("tts", "model"),
    "VOICE_PLAYBACK_BACKEND": ("playback", "backend"),
    "VOICE_PLAYBACK_DEVICE": ("playback", "alsa_device"),
    "VOICE_LOG_LEVEL": ("logging", "level"),
}


def _merge_dict(dst: dict[str, Any], src: Mapping[str, Any]) -> dict[str, Any]:
    for key, value in src.items():
        if isinstance(value, Mapping):
            node = dst.setdefault(key, {})
            if isinstance(node, Mapping):
                dst[key] = _merge_dict(dict(node), value)
            else:
                dst[key] = _merge_dict({}, value)
        else:
            dst[key] = value
    return dst


def _load_yaml(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
        if not isinstance(data, Mapping):
            raise ValueError(f"Config {path} must be a mapping")
        return dict(data)


def _apply_env(config: dict[str, Any]) -> dict[str, Any]:
    for env, path in ENV_MAPPING.items():
        if env in os.environ:
            _set_nested(config, path, os.environ[env])
    return config


def _set_nested(config: dict[str, Any], path: Iterable[str], value: Any) -> None:
    cur = config
    segments = list(path)
    for key in segments[:-1]:
        if key not in cur or not isinstance(cur[key], dict):
            cur[key] = {}
        cur = cur[key]
    cur[segments[-1]] = value


def load(path: str | os.PathLike[str] | None = None, *, overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    base = deepcopy(DEFAULT_CONFIG)
    cfg_path = Path(path) if path else Path("configs/voice.yaml")
    merged = _merge_dict(base, _load_yaml(cfg_path))
    merged = _apply_env(merged)
    if overrides:
        merged = _merge_dict(merged, overrides)
    return merged


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def override_from_pairs(section: str, pairs: Iterable[str]) -> dict[str, Any]:
    """Parse ``key=value`` overrides into a nested mapping."""

    result: dict[str, Any] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"Invalid override {pair!r}; expected key=value")
        key, value = pair.split("=", 1)
        section_map = result.setdefault(section, {})
        section_map[key.replace("-", "_")] = _auto(value)
    return result


def _auto(value: str) -> Any:
    lowered = value.lower()
    if lowered in {"true", "yes", "1"}:
        return True
    if lowered in {"false", "no", "0"}:
        return False
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def flatten(config: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in config.items():
        name = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
        if isinstance(value, Mapping):
            result.update(flatten(value, name))
        else:
            result[name] = value
    return result
