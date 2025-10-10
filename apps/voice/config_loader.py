# apps/voice/config_loader.py
"""
Config loader with comprehensive validation and schema enforcement.

Features:
- Schema validation with fail-fast or lenient modes
- Type and range checking
- Precedence: defaults < TOML < ENV < CLI
- Secret masking in logs
- Path resolution relative to TOML file
- Typo suggestions using difflib
"""

from __future__ import annotations

import difflib
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # py>=3.11
    import tomllib  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

__all__ = [
    "ConfigSchema",
    "ConfigLoader",
    "ValidationError",
    "load_and_validate",
    "print_effective_config",
]

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when config validation fails."""

    pass


@dataclass
class FieldSchema:
    """Schema for a single config field."""

    type: type | tuple[type, ...]
    required: bool = False
    choices: list[Any] | None = None
    min_value: float | int | None = None
    max_value: float | int | None = None
    default: Any = None


@dataclass
class ConfigSchema:
    """Complete schema for voice configuration."""

    # Schema for each section
    sections: dict[str, dict[str, FieldSchema]] = field(default_factory=dict)

    def __post_init__(self):
        """Initialize default schema."""
        if not self.sections:
            self._init_default_schema()

    def _init_default_schema(self):
        """Initialize the default voice config schema."""
        self.sections = {
            "logging": {
                "level": FieldSchema(type=str, choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO"),
            },
            "capture": {
                "device": FieldSchema(type=str, default="default"),
                "rate": FieldSchema(type=int, choices=[16000, 24000, 44100, 48000], default=16000),
                "channels": FieldSchema(type=int, choices=[1, 2], default=1),
                "format": FieldSchema(type=str, choices=["s16le", "s24le", "s32le"], default="s16le"),
                "backend": FieldSchema(type=str, choices=["alsa", "arecord", "pyaudio"], default="alsa"),
                "chunk_ms": FieldSchema(type=int, min_value=10, max_value=1000, default=20),
            },
            "playback": {
                "device": FieldSchema(type=str, default="default"),
                "backend": FieldSchema(type=str, choices=["alsa", "aplay", "pyaudio"], default="aplay"),
                "volume": FieldSchema(type=int, min_value=0, max_value=100, default=50),
                "ding": FieldSchema(type=dict, default={}),
            },
            "asr": {
                "backend": FieldSchema(type=str, choices=["openai", "vosk", "whisper"], default="openai"),
                "model": FieldSchema(type=str, default="whisper-1"),
                "transport": FieldSchema(type=str, choices=["file", "rest", "realtime"], default="file"),
                "language": FieldSchema(type=str, default="auto"),
            },
            "nlu": {
                "backend": FieldSchema(type=str, choices=["passthrough", "custom"], default="passthrough"),
            },
            "chat": {
                "backend": FieldSchema(type=str, choices=["openai", "ollama", "custom"], default="openai"),
                "model": FieldSchema(type=str, default="gpt-4o-mini"),
                "transport": FieldSchema(type=str, choices=["file", "rest", "realtime"], default="rest"),
                "language": FieldSchema(type=str, default="pl"),
                "system_prompt": FieldSchema(type=str, default=""),
                "max_tokens": FieldSchema(type=int, min_value=1, max_value=16384, default=150),
            },
            "tts": {
                "backend": FieldSchema(type=str, choices=["openai", "piper", "custom"], default="openai"),
                "format": FieldSchema(type=str, choices=["wav", "mp3", "pcm", "opus"], default="wav"),
                "voice": FieldSchema(type=str, default="alloy"),
                "transport": FieldSchema(type=str, choices=["file", "rest", "realtime"], default="file"),
                "rate": FieldSchema(type=(int, float), min_value=0.25, max_value=4.0, default=1.0),
            },
            "hotword": {
                "enabled": FieldSchema(type=bool, default=True),
                "engine": FieldSchema(type=str, choices=["porcupine", "ptt", "vosk"], default="ptt"),
            },
            "ptt": {
                "commit_on_stop": FieldSchema(type=bool, default=True),
                "silence_ms": FieldSchema(type=int, min_value=100, max_value=5000, default=700),
                "max_turn_ms": FieldSchema(type=int, min_value=1000, max_value=30000, default=6000),
            },
            "stream": {
                "protocol": FieldSchema(type=str, choices=["websocket", "http"], default="websocket"),
                "endpoint": FieldSchema(type=str, default=""),
                "auth": FieldSchema(type=str, default="env:OPENAI_API_KEY"),
                "chunk_ms": FieldSchema(type=int, min_value=10, max_value=100, default=20),
                "server_vad": FieldSchema(type=bool, default=False),
                "turn_end_silence_ms": FieldSchema(type=int, min_value=0, max_value=5000, default=900),
                "max_turn_ms": FieldSchema(type=int, min_value=1000, max_value=60000, default=8000),
                "send_partials": FieldSchema(type=bool, default=True),
                "barge_in": FieldSchema(type=bool, default=True),
            },
            "vad": {
                "enabled": FieldSchema(type=bool, default=False),
                "silence_ms": FieldSchema(type=int, min_value=100, max_value=5000, default=500),
            },
            "turn": {
                "max_turn_ms": FieldSchema(type=int, min_value=1000, max_value=60000, default=6000),
                "key_exit": FieldSchema(type=bool, default=True),
                "commit_on_key": FieldSchema(type=bool, default=True),
            },
            "service": {
                "beep": FieldSchema(type=bool, default=True),
                "beep_delay_ms": FieldSchema(type=int, min_value=0, max_value=2000, default=250),
                "hotword_enabled": FieldSchema(type=bool, default=True),
                "hotword_engine": FieldSchema(type=str, choices=["porcupine", "ptt", "vosk"], default="ptt"),
            },
            "save_audio": {
                "enabled": FieldSchema(type=bool, default=False),
                "dir": FieldSchema(type=str, default="./audio_logs"),
            },
        }


class ConfigLoader:
    """Loads and validates configuration with comprehensive error checking."""

    def __init__(self, schema: ConfigSchema | None = None, lenient: bool = False):
        """
        Initialize config loader.

        Args:
            schema: Config schema to validate against (uses default if None)
            lenient: If True, log warnings for unknown keys instead of raising errors
        """
        self.schema = schema or ConfigSchema()
        self.lenient = lenient
        self.unknown_keys: list[tuple[str, ...]] = []
        self.validation_errors: list[str] = []

    def load(
        self,
        path: str | Path | None = None,
        overrides: Mapping[str, Any] | None = None,
        toml_dir: Path | None = None,
    ) -> dict[str, Any]:
        """
        Load and validate configuration from TOML file with overrides.

        Args:
            path: Path to TOML config file
            overrides: Dict of overrides to apply after loading
            toml_dir: Base directory for resolving relative paths (auto-detected if None)

        Returns:
            Validated configuration dict

        Raises:
            ValidationError: If validation fails in fail-fast mode
        """
        # Load TOML
        config_path = self._resolve_path(path)
        toml_dir = toml_dir or config_path.parent

        with config_path.open("rb") as f:
            data = tomllib.load(f)

        # Apply overrides
        if overrides:
            data = self._deep_merge(data, dict(overrides))

        # Resolve paths relative to TOML directory
        data = self._resolve_relative_paths(data, toml_dir)

        # Validate
        self._validate(data)

        # Handle validation results
        if not self.lenient and (self.unknown_keys or self.validation_errors):
            error_msg = self._format_validation_errors()
            raise ValidationError(error_msg)

        if self.lenient and (self.unknown_keys or self.validation_errors):
            for msg in self._format_validation_warnings():
                logger.warning(msg)

        return data

    def _resolve_path(self, path: str | Path | None) -> Path:
        """Resolve config file path."""
        if path is None:
            # Default to config/voice.toml
            repo_root = Path(__file__).resolve().parents[2]
            return repo_root / "config" / "voice.toml"
        p = Path(path).expanduser()
        if p.is_absolute():
            return p
        # Try relative to config dir first
        repo_root = Path(__file__).resolve().parents[2]
        config_path = repo_root / "config" / p
        if config_path.exists():
            return config_path
        # Otherwise relative to cwd
        return Path.cwd() / p

    def _deep_merge(self, base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
        """Deep merge overrides into base config."""
        result = dict(base)
        for key, value in overrides.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def _resolve_relative_paths(self, config: dict[str, Any], base_dir: Path) -> dict[str, Any]:
        """Resolve relative paths in config relative to TOML file directory."""
        result = dict(config)

        # Path fields that should be resolved
        path_fields = {
            ("save_audio", "dir"),
            ("asr", "model_path"),
            ("tts", "model_path"),
        }

        for section, field_name in path_fields:
            if section in result and isinstance(result[section], dict):
                if field_name in result[section]:
                    path_str = str(result[section][field_name])
                    if path_str.startswith("~"):
                        result[section][field_name] = str(Path(path_str).expanduser())
                    elif not Path(path_str).is_absolute():
                        result[section][field_name] = str((base_dir / path_str).resolve())

        return result

    def _validate(self, config: dict[str, Any]) -> None:
        """Validate config against schema."""
        self.unknown_keys = []
        self.validation_errors = []

        # Check for unknown sections
        for section in config:
            if section not in self.schema.sections:
                self.unknown_keys.append((section,))
                suggestion = self._suggest_typo(section, self.schema.sections.keys())
                if suggestion and not self.lenient:
                    self.validation_errors.append(f"Unknown section '{section}'. Did you mean '{suggestion}'?")

        # Validate each known section
        for section, section_schema in self.schema.sections.items():
            if section not in config:
                continue

            section_data = config[section]
            if not isinstance(section_data, dict):
                self.validation_errors.append(f"Section '{section}' must be a dict, got {type(section_data).__name__}")
                continue

            # Check for unknown keys in section
            for key in section_data:
                if key not in section_schema:
                    self.unknown_keys.append((section, key))
                    suggestion = self._suggest_typo(key, section_schema.keys())
                    if suggestion and not self.lenient:
                        self.validation_errors.append(
                            f"Unknown key '{section}.{key}'. Did you mean '{section}.{suggestion}'?"
                        )

            # Validate field values
            for field_name, field_schema in section_schema.items():
                if field_name not in section_data:
                    if field_schema.required:
                        self.validation_errors.append(f"Required field '{section}.{field_name}' is missing")
                    continue

                value = section_data[field_name]
                self._validate_field(section, field_name, value, field_schema)

        # Special validation: PTT ignored when server_vad=true and hotword disabled
        if self._should_ignore_ptt(config):
            if "ptt" in config and not self.lenient:
                logger.info("[ptt] section is ignored when hotword.enabled=false and stream.server_vad=true")

    def _should_ignore_ptt(self, config: dict[str, Any]) -> bool:
        """Check if PTT section should be ignored."""
        hotword_cfg = config.get("hotword", {})
        stream_cfg = config.get("stream", {})
        return not hotword_cfg.get("enabled", True) and stream_cfg.get("server_vad", False)

    def _validate_field(self, section: str, field: str, value: Any, schema: FieldSchema) -> None:
        """Validate a single field value."""
        # Type check
        if not isinstance(value, schema.type):
            self.validation_errors.append(
                f"Field '{section}.{field}' must be {schema.type}, got {type(value).__name__}"
            )
            return

        # Choices check
        if schema.choices is not None and value not in schema.choices:
            self.validation_errors.append(f"Field '{section}.{field}' must be one of {schema.choices}, got '{value}'")

        # Range check for numeric types
        if isinstance(value, (int, float)):
            if schema.min_value is not None and value < schema.min_value:
                self.validation_errors.append(f"Field '{section}.{field}' must be >= {schema.min_value}, got {value}")
            if schema.max_value is not None and value > schema.max_value:
                self.validation_errors.append(f"Field '{section}.{field}' must be <= {schema.max_value}, got {value}")

    def _suggest_typo(self, key: str, known_keys: list[str] | Any) -> str | None:
        """Suggest correction for typo using difflib."""
        matches = difflib.get_close_matches(key, list(known_keys), n=1, cutoff=0.6)
        return matches[0] if matches else None

    def _format_validation_errors(self) -> str:
        """Format validation errors for exception message."""
        lines = ["Configuration validation failed:"]

        if self.unknown_keys:
            lines.append("\nUnknown keys:")
            for key_path in sorted(self.unknown_keys):
                key_str = ".".join(key_path)
                lines.append(f"  - {key_str}")

        if self.validation_errors:
            lines.append("\nValidation errors:")
            for error in self.validation_errors:
                lines.append(f"  - {error}")

        return "\n".join(lines)

    def _format_validation_warnings(self) -> list[str]:
        """Format validation issues as warning messages."""
        warnings = []

        for key_path in sorted(self.unknown_keys):
            key_str = ".".join(key_path)
            warnings.append(f"Unknown config key '{key_str}'")

        for error in self.validation_errors:
            warnings.append(error)

        return warnings


def mask_secrets(config: dict[str, Any], keep_tail: int = 4) -> dict[str, Any]:
    """
    Mask secrets in config for logging.

    Args:
        config: Configuration dict
        keep_tail: Number of characters to keep at end of secret

    Returns:
        Config with secrets masked
    """
    result = {}
    secret_patterns = {"key", "token", "secret", "password", "auth"}

    for key, value in config.items():
        if isinstance(value, dict):
            result[key] = mask_secrets(value, keep_tail)
        elif isinstance(value, str) and any(pattern in key.lower() for pattern in secret_patterns):
            # Mask the secret
            if len(value) <= keep_tail:
                result[key] = "***"
            else:
                result[key] = ("*" * (len(value) - keep_tail)) + value[-keep_tail:]
        else:
            result[key] = value

    return result


def load_and_validate(
    path: str | Path | None = None,
    overrides: Mapping[str, Any] | None = None,
    lenient: bool = False,
) -> dict[str, Any]:
    """
    Load and validate config (convenience function).

    Args:
        path: Path to config file
        overrides: Dict of overrides
        lenient: If True, warn on unknown keys instead of raising

    Returns:
        Validated config dict

    Raises:
        ValidationError: If validation fails in fail-fast mode
    """
    loader = ConfigLoader(lenient=lenient)
    return loader.load(path, overrides)


def print_effective_config(config: dict[str, Any], mask: bool = True) -> None:
    """
    Print effective configuration as TOML.

    Args:
        config: Configuration dict
        mask: If True, mask secrets
    """
    import tomli_w

    if mask:
        config = mask_secrets(config)

    toml_str = tomli_w.dumps(config)
    print(toml_str)
