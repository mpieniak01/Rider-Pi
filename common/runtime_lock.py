"""Serialize task mutations and separate maintenance processes on Linux."""

from __future__ import annotations

import fcntl
import os
import time
from contextlib import contextmanager
from pathlib import Path


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
