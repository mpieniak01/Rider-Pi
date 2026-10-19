from __future__ import annotations

import atexit
import fcntl
import os
import sys

from common.runtime_lock import open_owned


def single_instance(lock_path="/tmp/rider-motion.lock"):
    """Keep one stable inode for all owners, including after process shutdown."""
    fd = None
    try:
        fd = open_owned(lock_path)
        fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
    except OSError as error:
        if fd is not None:
            os.close(fd)
        print(f"[PIDLOCK] another instance running or unsafe lock: {lock_path}", file=sys.stderr)
        raise SystemExit(1) from error

    def _cleanup():
        try:
            os.close(fd)
        except OSError:
            # A caller may already have closed the returned descriptor.
            pass

    # Never unlink: another process can already hold this same inode.
    atexit.register(_cleanup)
    return fd
