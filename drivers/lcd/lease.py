"""Cross-process LCD ownership; descriptors release automatically on exit."""

from __future__ import annotations

import fcntl
import os
import pwd
import stat
from pathlib import Path

from common.secure_files import directory


class LCDLease:
    def __init__(self):
        path = Path(os.getenv("RIDER_LCD_OWNER_LOCK", "/tmp/rider-lcd-owner.lock"))
        with directory(path.parent) as parent:
            fd = os.open(
                path.name, os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o644, dir_fd=parent
            )
            try:
                allowed = {0, os.geteuid()}
                if os.geteuid() == 0:
                    allowed.add(pwd.getpwnam("pi").pw_uid)
                info = os.fstat(fd)
                entry = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid not in allowed
                    or info.st_nlink != 1
                    or info.st_mode & 0o022
                    or (info.st_dev, info.st_ino) != (entry.st_dev, entry.st_ino)
                ):
                    raise PermissionError("unsafe_lcd_owner_lock")
                self.handle = os.fdopen(fd, "rb")
            except BaseException:
                os.close(fd)
                raise
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
