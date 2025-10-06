# apps/voice/config.py
"""
Configuration loader for the voice stack (TOML-first with legacy YAML fallback).

This module implements the SINGLE SOURCE OF TRUTH for voice configuration.
See docs/CONFIG_POLICY.md for full policy documentation.

Precedence:
1. Internal defaults (DEFAULT_CONFIG).
2. File: VOICE_CONFIG (if set) or first existing among:
   - RIDER_CONFIG_DIR/voice.toml  (recommended: set via ENV)
   - ./config/voice.toml           (repo default)
   - (legacy) ./configs/voice.yaml [DEPRECATED – will be removed later]
3. Environment variables (prefixed VOICE_).
4. CLI overrides (mapping), typically from apps.voice.cli.

Merging is deep (dict-recursive). Returned value is a plain dict.

Environment variables:
- VOICE_CONFIG: explicit path to config file (highest priority)
- RIDER_CONFIG_DIR: directory containing voice.toml (e.g., /etc/rider)
- VOICE_*: individual setting overrides (e.g., VOICE_ASR_BACKEND=vosk)

Example usage:
    from apps.voice import config
    
    # Load with defaults
    cfg = config.load()
    
    # Load with overrides
    cfg = config.load(overrides={"asr": {"backend": "vosk"}})
    
    # Load specific file
    cfg = config.load("config/voice_streaming.toml")
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

# ───────────────────────────────────────────────────────────────────────────────
# Defaults (spójne z realtime i ALSA WM8960)
# ───────────────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG: dict[str, Any] = {
    "capture": {
        "backend": "alsa",  # alsa|command
        "device": "default",  # alias np. plughw:wm8960soundcard,0
        "sample_rate": 16_000,
        "channels": 1,
        "frame_ms": 20,
        "buffer_seconds": 0.0,
        "command": None,  # dla backend=command
        "extra_args": [],  # dodatkowe argumenty dla arecord itp.
    },
    "hotword": {
        "enabled": False,
        "engine": "ptt",  # ptt|nyumaya|porcupine
        "model": None,
        "sensitivity": 0.6,
        "auto_gain": 1.0,
        "threshold": 0.6,
    },
    "asr": {
        "backend": "openai",  # openai|vosk|faster-whisper|whispercpp
        "transport": "file",  # file|realtime
        "model": "gpt-4o-mini-transcribe",
        "language": "pl",
        "temperature": 0.0,
        "prompt": None,
        "vosk_model_dir": "models/vosk",
        "whisper_model": "medium",
        "input_encoding": "s16le",
        # NEW: VAD (dawniej top-level 'vad')
        "vad": {
            "enabled": True,
            "aggressiveness": 2,  # 0..3
            "start_ms": 200,
            "end_ms": 700,
        },
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
        "max_tokens": 70,
    },
    "tts": {
        "backend": "openai",  # openai|piper
        "transport": "file",  # file|realtime
        "model": "gpt-4o-mini-tts",
        "voice": "alloy",
        "format": "mp3",
        "piper_model": None,
        "piper_config": None,
    },
    "playback": {
        "backend": "auto",  # auto|pulse|alsa
        "alsa_device": "default",  # alias np. plughw:wm8960soundcard,0
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
        "save_format": "wav",  # "wav" | "mp3"
        "filename_pattern": "%Y%m%d_%H%M%S",  # strftime dla nazw
        "history_size": 20,
        "beep": True,
        "beep_delay_ms": 250,
        "turn": {
            "max_turn_ms": 6000,
            "key_exit": True,
            "commit_on_key": True,
        },
    },
    "web": {
        "host": "127.0.0.1",
        "port": 8092,
        "allow_origins": ["*"],
    },
    "logging": {
        "level": "INFO",
    },
    # Streaming (realtime WebSocket)
    "stream": {
        "protocol": "websocket",
        "endpoint": "",
        "auth": "env:OPENAI_API_KEY",  # jawnie wspieramy env
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

# ───────────────────────────────────────────────────────────────────────────────
# ENV mapping (rozszerzony o nowe ścieżki)
# ───────────────────────────────────────────────────────────────────────────────

ENV_MAPPING: dict[str, tuple[str, ...]] = {
    "VOICE_CAPTURE_BACKEND": ("capture", "backend"),
    "VOICE_CAPTURE_DEVICE": ("capture", "device"),
    "VOICE_CAPTURE_COMMAND": ("capture", "command"),
    "VOICE_CAPTURE_SAMPLE_RATE": ("capture", "sample_rate"),
    "VOICE_CAPTURE_CHANNELS": ("capture", "channels"),
    # Legacy VAD env → przeniesione do asr.vad.*
    "VOICE_VAD_MODE": ("asr", "vad", "aggressiveness"),
    "VOICE_VAD_TAIL_MS": ("asr", "vad", "end_ms"),
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

# ───────────────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────────────


def _build_known_keys_for_warning() -> dict[str, Any]:
    """
    Zwraca schemat kluczy uznawanych za poprawne, łącznie z LEGACY,
    aby nie straszyć ostrzeżeniami przed normalizacją.
    """
    known = deepcopy(DEFAULT_CONFIG)

    # LEGACY: top-level 'vad'
    known["vad"] = {
        "enabled": True,
        "mode": 2,
        "frame_ms": 20,
        "tail_ms": 350,
        "max_len_ms": 8000,
        "energy_gate_dbfs": -48.0,
    }
    # LEGACY: stream.* przeniesione do stream.reconnect
    known["stream"].update(
        {
            "max_retries": 6,
            "base_ms": 250,
            "max_ms": 5000,
        }
    )
    # LEGACY: service.logging → logging
    known["service"]["logging"] = {"level": "INFO"}
    # LEGACY: playback.device → playback.alsa_device
    known["playback"]["device"] = "default"
    # LEGACY: schema (dowolna wartość) – ignorujemy
    known["schema"] = {}

    return known


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


# ───────────────────────────────────────────────────────────────────────────────
# Legacy normalizer (mapuje stare klucze -> nowe ścieżki)
# ───────────────────────────────────────────────────────────────────────────────


def _normalize_legacy(config: dict[str, Any]) -> dict[str, Any]:
    cfg = config

    # 1) top-level 'vad' → asr.vad.*
    if isinstance(cfg.get("vad"), Mapping):
        legacy_vad = dict(cfg.pop("vad"))
        asr_vad = cfg.setdefault("asr", {}).setdefault("vad", {})
        if "enabled" in legacy_vad:
            asr_vad.setdefault("enabled", legacy_vad["enabled"])
        if "mode" in legacy_vad:
            asr_vad.setdefault("aggressiveness", legacy_vad["mode"])
        if "tail_ms" in legacy_vad:
            asr_vad.setdefault("end_ms", legacy_vad["tail_ms"])
        if "frame_ms" in legacy_vad and "start_ms" not in asr_vad:
            try:
                asr_vad.setdefault("start_ms", int(legacy_vad["frame_ms"]))
            except Exception:
                pass
        # energy_gate_dbfs / max_len_ms – pomijamy

    # 2) stream.{max_retries,base_ms,max_ms} → stream.reconnect.*
    stream = cfg.get("stream")
    if isinstance(stream, Mapping):
        s = dict(stream)
        moved = False
        for k in ("max_retries", "base_ms", "max_ms"):
            if k in s:
                cfg.setdefault("stream", {}).setdefault("reconnect", {})[k] = s[k]
                moved = True
        if moved:
            for k in ("max_retries", "base_ms", "max_ms"):
                cfg["stream"].pop(k, None)

    # 3) service.logging.level → logging.level
    if isinstance(cfg.get("service"), Mapping):
        svc = cfg["service"]
        if isinstance(svc.get("logging"), Mapping):
            lvl = svc["logging"].get("level")
            if lvl:
                cfg.setdefault("logging", {})["level"] = lvl
            svc.pop("logging", None)

    # 4) playback.device → playback.alsa_device
    if isinstance(cfg.get("playback"), Mapping):
        pb = cfg["playback"]
        if "device" in pb and "alsa_device" not in pb:
            pb["alsa_device"] = pb.pop("device")

    # 5) schema → ignoruj
    cfg.pop("schema", None)

    return cfg


def _normalize_aliases(cfg: dict[str, Any]) -> dict[str, Any]:
    """
    Spójnik aliasów:
    - capture: jeżeli jest 'alsa_device' a brak 'device' → device = alsa_device
    - playback: jeżeli jest tylko 'device' → alsa_device = device
    """
    cap = cfg.get("capture", {}) or {}
    if "device" not in cap and "alsa_device" in cap:
        cap["device"] = cap["alsa_device"]
    cfg["capture"] = cap

    pb = cfg.get("playback", {}) or {}
    if "alsa_device" not in pb and "device" in pb:
        pb["alsa_device"] = pb["device"]
    cfg["playback"] = pb
    return cfg


# ───────────────────────────────────────────────────────────────────────────────
# Public API
# ───────────────────────────────────────────────────────────────────────────────


def load(path: str | os.PathLike[str] | None = None, *, overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    base = deepcopy(DEFAULT_CONFIG)
    cfg_path, kind = _discover_config_path(path)

    loaded_config: dict[str, Any] = {}
    if cfg_path and kind == "toml":
        loaded_config = _load_toml(cfg_path)
        # Warn with LEGACY schema included to avoid noise
        _warn_unknown_keys(loaded_config, _build_known_keys_for_warning())
    elif cfg_path and kind == "yaml":
        print("[voice.config] WARNING: loading legacy YAML from configs/voice.yaml (DEPRECATED)")
        loaded_config = _load_yaml(cfg_path)
        _warn_unknown_keys(loaded_config, _build_known_keys_for_warning())
    else:
        loaded_config = {}

    # Merge file over defaults
    merged = _merge_dict(base, loaded_config)
    # Normalize legacy → mapuj stare klucze do nowych
    merged = _normalize_legacy(merged)
    # **Alias fixy** (capture/playback)
    merged = _normalize_aliases(merged)
    # Apply ENV
    merged = _apply_env(merged)
    # CLI overrides last
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
