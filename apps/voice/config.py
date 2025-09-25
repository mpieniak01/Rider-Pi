# apps/voice/config.py
"""
Configuration loader for the voice stack (TOML-first with legacy YAML fallback).

Precedence:
1. Internal defaults (DEFAULT_CONFIG).
2. File: VOICE_CONFIG (if set) or first existing among:
   - RIDER_CONFIG_DIR/voice.toml
   - ./config/voice.toml
   - (legacy) ./configs/voice.yaml  [DEPRECATED – will be removed later]
3. Environment variables (prefixed VOICE_).
4. CLI overrides (mapping), typically from apps.voice.cli.

Merging is deep (dict-recursive). Returned value is a plain dict.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

# TOML: stdlib on 3.11; tomli on 3.9/3.10
try:
    import tomllib  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore
    except Exception:  # pragma: no cover
        tomllib = None  # type: ignore

# YAML only when actually loading a .yaml
try:  # pragma: no cover
    import yaml
except Exception:  # pragma: no cover
    yaml = None  # type: ignore

DEFAULT_CONFIG: dict[str, Any] = {
    # RPi-friendly defaults (even if TOML is missing)
    "capture": {
        "backend": "alsa",  # alsa|pulse|command
        "device": "default",
        "sample_rate": 16_000,
        "channels": 1,
        "frame_ms": 20,
        "buffer_seconds": 0.0,
        "command": None,
    },
    "vad": {
        "enabled": True,
        "mode": 2,  # 0..3, 2 ~= balanced
        "frame_ms": 20,
        "tail_ms": 350,
        "max_len_ms": 8000,
        "energy_gate_dbfs": -48.0,
    },
    "hotword": {
        "enabled": False,  # avoid waiting for a model by default
        "engine": "nyumaya",  # nyumaya|porcupine|ptt|off
        "model": None,
        "sensitivity": 0.6,
        "auto_gain": 1.0,
        "threshold": 0.6,
    },
    "asr": {
        "backend": "openai",  # openai|vosk|faster-whisper|whispercpp
        "transport": "file",  # file|realtime
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
        "transport": "rest",  # rest|realtime
        "model": "gpt-4o-mini",
        "system_prompt": "You are Rider-Pi, a friendly voice assistant.",
        "max_history": 4,
        "max_tokens": 70,  # Common parameter for chat
    },
    "tts": {
        "backend": "openai",  # openai|piper
        "transport": "file",  # file|realtime
        "model": "gpt-4o-mini-tts",
        "voice": "alloy",
        "format": "mp3",  # stream-friendly for mpg123
        "piper_model": None,
        "piper_config": None,
    },
    "playback": {
        "backend": "auto",  # auto|pulse|alsa
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
    # Streaming configuration (for realtime WebSocket mode)
    "stream": {
        "protocol": "websocket",
        "endpoint": "",
        "auth": "",
        "chunk_ms": 20,
        "sample_rate": 16000,
        "turn_end_silence_ms": 700,
        "max_turn_ms": 6000,
        "send_partials": True,
        "server_vad": True,
        "local_vad_fallback": True,
        "ping_interval_s": 10,
        "reconnect": {
            "max_retries": 6,
            "base_ms": 250,
            "max_ms": 5000,
        },
        "audio": {
            "jitter_buffer_ms": 120,
            "barge_in": True,
        },
    },
}

# Minimal, pragmatic ENV mapping (you can ignore these if you keep everything in TOML)
ENV_MAPPING: dict[str, tuple[str, ...]] = {
    "VOICE_CAPTURE_BACKEND": ("capture", "backend"),
    "VOICE_CAPTURE_DEVICE": ("capture", "device"),
    "VOICE_CAPTURE_COMMAND": ("capture", "command"),
    "VOICE_CAPTURE_SAMPLE_RATE": ("capture", "sample_rate"),
    "VOICE_CAPTURE_CHANNELS": ("capture", "channels"),
    "VOICE_VAD_MODE": ("vad", "mode"),
    "VOICE_VAD_TAIL_MS": ("vad", "tail_ms"),
    "VOICE_ASR_BACKEND": ("asr", "backend"),
    "VOICE_ASR_MODEL": ("asr", "model"),
    "VOICE_ASR_LANG": ("asr", "language"),
    "VOICE_TTS_BACKEND": ("tts", "backend"),
    "VOICE_TTS_VOICE": ("tts", "voice"),
    "VOICE_TTS_MODEL": ("tts", "model"),
    "VOICE_TTS_FORMAT": ("tts", "format"),
    "VOICE_PLAYBACK_BACKEND": ("playback", "backend"),
    "VOICE_PLAYBACK_DEVICE": ("playback", "alsa_device"),
    "VOICE_PLAYBACK_VOLUME": ("playback", "volume"),
    "VOICE_LOG_LEVEL": ("logging", "level"),
}


def _warn_unknown_keys(config: dict[str, Any], known_config: dict[str, Any], prefix: str = "") -> None:
    """Warn about unknown keys in config, compared to known_config structure."""
    for key, value in config.items():
        full_key = f"{prefix}.{key}" if prefix else key
        
        if key not in known_config:
            print(f"[voice.config] WARNING: unknown config key '{full_key}' (ignored)")
        elif isinstance(value, Mapping) and isinstance(known_config[key], Mapping):
            _warn_unknown_keys(dict(value), dict(known_config[key]), full_key)


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


def _load_toml(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    if tomllib is None:
        raise RuntimeError("TOML config requires tomllib/tomli, but none is available")
    with path.open("rb") as f:
        data = tomllib.load(f) or {}
    if not isinstance(data, Mapping):
        raise ValueError(f"Config {path} must be a mapping")
    return dict(data)


def _load_yaml(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    if yaml is None:
        raise RuntimeError("YAML config requires PyYAML (python3-yaml)")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, Mapping):
        raise ValueError(f"Config {path} must be a mapping")
    return dict(data)


def _apply_env(config: dict[str, Any]) -> dict[str, Any]:
    # Apply ENV with basic type coercion (numbers/bools), not raw strings
    for env, path in ENV_MAPPING.items():
        if env in os.environ:
            _set_nested(config, path, _auto(os.environ[env]))
    return config


def _set_nested(config: dict[str, Any], path: Iterable[str], value: Any) -> None:
    cur = config
    segments = list(path)
    for key in segments[:-1]:
        if key not in cur or not isinstance(cur[key], dict):
            cur[key] = {}
        cur = cur[key]
    cur[segments[-1]] = value


def _discover_config_path(cli_path: str | os.PathLike[str] | None) -> tuple[Path | None, str]:
    """Return (path, kind) where kind in {"toml","yaml",""}."""
    if cli_path:
        p = Path(cli_path)
        ext = p.suffix.lower()
        if ext == ".toml":
            return p, "toml"
        if ext in {".yaml", ".yml"}:
            return p, "yaml"
        # No/unknown ext – try TOML first, then YAML
        if p.exists():
            return p, "toml"
        return None, ""

    # ENV override
    env_p = os.getenv("VOICE_CONFIG")
    if env_p:
        return _discover_config_path(env_p)

    # RIDER_CONFIG_DIR first
    rid = os.getenv("RIDER_CONFIG_DIR")
    if rid:
        p = Path(rid) / "voice.toml"
        if p.exists():
            return p, "toml"

    # repo-local preferred
    p = Path("config/voice.toml")
    if p.exists():
        return p, "toml"

    # legacy fallback (deprecated)
    p = Path("configs/voice.yaml")
    if p.exists():
        return p, "yaml"

    return None, ""


def load(path: str | os.PathLike[str] | None = None, *, overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    base = deepcopy(DEFAULT_CONFIG)
    cfg_path, kind = _discover_config_path(path)
    if cfg_path and kind == "toml":
        loaded_config = _load_toml(cfg_path)
        # Warn about unknown keys before merging
        _warn_unknown_keys(loaded_config, DEFAULT_CONFIG)
        merged = _merge_dict(base, loaded_config)
    elif cfg_path and kind == "yaml":
        print("[voice.config] WARNING: loading legacy YAML from configs/voice.yaml (DEPRECATED)")
        loaded_config = _load_yaml(cfg_path)
        # Warn about unknown keys before merging
        _warn_unknown_keys(loaded_config, DEFAULT_CONFIG)
        merged = _merge_dict(base, loaded_config)
    else:
        merged = base  # no file found

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
