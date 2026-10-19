"""Directory-anchored writes for trusted runtime paths on Linux."""

from __future__ import annotations

import os
import secrets
import stat
from contextlib import contextmanager
from pathlib import Path

_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _check_directory(fd, private=False):
    info = os.fstat(fd)
    if info.st_uid not in {0, os.geteuid()} or info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX:
        raise PermissionError("unsafe_runtime_directory")
    if private and (info.st_uid != os.geteuid() or info.st_mode & 0o077):
        raise PermissionError("private_runtime_directory_required")


@contextmanager
def directory(path, *, private=False):
    """Open every directory component without following links; pin the final fd."""
    path = Path(path)
    if ".." in path.parts:
        raise ValueError("runtime_path_must_not_traverse")
    path = path.absolute()
    descriptor = os.open(path.anchor, _DIRECTORY_FLAGS)
    try:
        for part in path.parts[1:]:
            _check_directory(descriptor)
            try:
                child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            except FileNotFoundError:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    # Another creator must still pass the no-link/owner checks.
                    pass
                child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        _check_directory(descriptor, private)
        yield descriptor
    finally:
        os.close(descriptor)


def atomic_write(path, writer, *, private=False, replace=True):
    """Write mode0600, then publish a complete file without following target links."""
    path = Path(path)
    if path.name in {"", ".", ".."}:
        raise ValueError("runtime_filename_required")
    with directory(path.parent, private=private) as descriptor:
        temporary = ".rider-write-" + secrets.token_hex(16) + ".tmp"
        handle = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=descriptor,
        )
        try:
            try:
                stream = os.fdopen(handle, "wb")
            except BaseException:
                os.close(handle)
                raise
            with stream:
                writer(stream)
            if replace:
                os.replace(temporary, path.name, src_dir_fd=descriptor, dst_dir_fd=descriptor)
            else:
                # Publish a new recording atomically; an existing name is never overwritten.
                os.link(temporary, path.name, src_dir_fd=descriptor, dst_dir_fd=descriptor, follow_symlinks=False)
        finally:
            try:
                os.unlink(temporary, dir_fd=descriptor)
            except FileNotFoundError:
                pass
