"""Common helpers shared across the voice assistant modules."""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

from . import logging as voice_logging

_PROFILE_FILES = [Path("~/.bash_profile").expanduser(), Path("~/.profile").expanduser()]


def _strip_quotes(value: str) -> str:
    if not value:
        return value
    value = value.strip()
    if len(value) >= 2 and value[0] in {'"', "'"} and value[-1] == value[0]:
        return value[1:-1]
    return value


@lru_cache(maxsize=1)
def _load_key_from_profiles() -> Optional[str]:
    for path in _PROFILE_FILES:
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                match = re.match(r"\s*export\s+OPENAI_API_KEY\s*=\s*(.+)", line)
                if not match:
                    continue

                raw = match.group(1).strip()
                # usuń komentarz na końcu linii (ignorujemy # wewnątrz cudzysłowów)
                buf: list[str] = []
                quote: str | None = None
                for char in raw:
                    if char in {'"', "'"} and quote is None:
                        quote = char
                        buf.append(char)
                        continue
                    if quote is not None and char == quote:
                        quote = None
                        buf.append(char)
                        continue
                    if char == '#' and quote is None:
                        break
                    buf.append(char)
                raw = ''.join(buf).strip()
                key = _strip_quotes(raw)
                if key:
                    return key
        except OSError:
            continue
    return None


def ensure_openai_key(logger: voice_logging.VoiceLogger | None = None) -> Optional[str]:
    """Ensure that ``OPENAI_API_KEY`` is present in the environment."""

    key = os.getenv("OPENAI_API_KEY")
    if key:
        return key

    loaded = _load_key_from_profiles()
    if loaded:
        os.environ["OPENAI_API_KEY"] = loaded
        if logger:
            logger.event("voice.key.loaded", source="profile")
        return loaded

    if logger:
        logger.warning("voice.key.missing")
    return None
