"""Cross-process LCD ownership; descriptors release automatically on exit."""

from __future__ import annotations

import fcntl
import os


class LCDLease:
    def __init__(self):
        path = os.getenv("RIDER_LCD_OWNER_LOCK", "/tmp/rider-lcd-owner.lock")
        self.handle = os.fdopen(os.open(path, os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW, 0o644), "rb")
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.handle.close()
            raise RuntimeError("lcd_owned_or_unknown") from error

    def close(self):
        self.handle.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
