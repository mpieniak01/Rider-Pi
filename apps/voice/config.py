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


EXAMPLE_USAGE ="""

EXAMPLE_USAGE = (
    "Example usage:\n"
    "\n"
    "from apps.voice import config\n"
    "\n"
    "# Load with defaults\n"
    "cfg = config.load()\n"
    "\n"
    "# Load with overrides\n"
    'cfg = config.load(overrides={"asr": {"backend": "vosk"}})\n'
    "\n"
    "# Load specific file\n"
    'cfg = config.load("config/voice_streaming.toml")\n'
)
