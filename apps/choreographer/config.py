"""Configuration loading for choreographer module."""

from __future__ import annotations

import os
from pathlib import Path

try:
    import tomllib  # type: ignore[attr-defined]
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        raise ImportError("tomli is required for Python < 3.11. Install with: pip install tomli") from None


def load_choreography_config(config_path: str | None = None) -> dict:
    """
    Load choreography configuration from TOML file.

    Args:
        config_path: Path to config file. If None, uses default from repo.

    Returns:
        Dictionary with choreography mappings.
    """
    if config_path is None:
        repo_root = Path(__file__).resolve().parents[2]
        config_path = str(repo_root / "config" / "choreography.toml")

    if not os.path.exists(config_path):
        return {"mappings": []}

    with open(config_path, "rb") as f:
        config = tomllib.load(f)

    return config


def validate_config(config: dict) -> bool:
    """
    Validate choreography configuration structure.

    Args:
        config: Configuration dictionary to validate.

    Returns:
        True if valid, False otherwise.
    """
    if "mappings" not in config:
        return False

    for mapping in config.get("mappings", []):
        if "trigger" not in mapping:
            return False
        if "actions" not in mapping:
            return False

        trigger = mapping["trigger"]
        if "topic" not in trigger or "match" not in trigger:
            return False

    return True
