"""Serialize task mutations and separate maintenance processes on Linux."""

from __future__ import annotations

import fcntl
import os
import stat
import time
from contextlib import contextmanager
from pathlib import Path

from common.secure_files import directory


@contextmanager
def exclusive(path: Path, timeout_s: float = 2.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o660)
    try:
        if os.geteuid() == 0:
            parent = path.parent.stat()
            os.fchown(fd, parent.st_uid, parent.st_gid)
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("orchestration lock busy") from None
                time.sleep(0.02)
        # Existing callers ignore the value. Resource owners may record state
        # through this same locked descriptor without opening a second owner.
        yield fd
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def open_owned(path):
    """Return a private regular lock fd, refusing links and foreign/replaced inodes."""
    path = Path(path)
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    with directory(path.parent) as descriptor:
        try:
            fd = os.open(path.name, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=descriptor)
        except FileExistsError:
            fd = os.open(path.name, flags, dir_fd=descriptor)
        try:
            info = os.fstat(fd)
            entry = os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_nlink != 1
                or info.st_mode & 0o022
                or (info.st_dev, info.st_ino) != (entry.st_dev, entry.st_ino)
            ):
                raise PermissionError("unsafe_runtime_lock")
            os.fchmod(fd, 0o600)
            return fd
        except BaseException:
            os.close(fd)
            raise
