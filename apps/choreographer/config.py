from __future__ import annotations

"""Configuration loading for choreographer module."""

import os
import tomllib
from pathlib import Path


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
