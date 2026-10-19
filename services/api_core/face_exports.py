"""Bounded PNG exports; filenames never select arbitrary filesystem locations."""

from __future__ import annotations

import os
import re
import secrets
import stat
from pathlib import Path

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
    """Pin the export directory and replace entries without following final links."""
    directory = destination.parent
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = None
    try:
        info = os.fstat(descriptor)
        if info.st_uid not in {0, os.geteuid()} or info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX:
            raise PermissionError("unsafe_face_export_directory")
        name = ".rider-face-" + secrets.token_hex(16) + ".tmp"
        handle = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
        temporary = name
        try:
            stream = os.fdopen(handle, "wb")
        except Exception:
            os.close(handle)
            raise
        with stream:
            stream.write(png)
        os.replace(temporary, destination.name, src_dir_fd=descriptor, dst_dir_fd=descriptor)
        temporary = None
    finally:
        try:
            if temporary is not None:
                try:
                    os.unlink(temporary, dir_fd=descriptor)
                except FileNotFoundError:
                    pass
        finally:
            os.close(descriptor)
