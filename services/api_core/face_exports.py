"""Bounded PNG exports; filenames never select arbitrary filesystem locations."""

from __future__ import annotations

import os
import re
from pathlib import Path

from common.secure_files import atomic_write

_NAME = re.compile(r"face(?:_[A-Za-z0-9_-]{1,100})?\.png")


def target(value: str) -> Path:
    """Accept one face PNG basename or its absolute path in the configured root."""
    root = Path(os.getenv("FACE_RENDER_DIR", "/tmp"))
    if not root.is_absolute():
        raise OSError("face_export_directory_must_be_absolute")
    if not isinstance(value, str) or not value or ".." in Path(value).parts:
        raise ValueError("invalid_face_output")
    requested = Path(value)
    if not _NAME.fullmatch(value if not requested.is_absolute() else requested.name):
        raise ValueError("invalid_face_output")
    if requested.is_absolute() and requested.parent != root:
        raise ValueError("invalid_face_output")
    return root / requested.name


def save(destination: Path, png: bytes) -> None:
    """Publish a private PNG through checked, pinned directory components."""
    atomic_write(destination, lambda stream: stream.write(png))
