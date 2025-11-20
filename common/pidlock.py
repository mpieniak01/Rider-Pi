from __future__ import annotations

import atexit
import fcntl
import os
import sys


def single_instance(lock_path="/tmp/rider-motion.lock"):
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.write(fd, str(os.getpid()).encode())
    except OSError:
        print(f"[PIDLOCK] another instance running (lock: {lock_path})", file=sys.stderr)
        sys.exit(1)

    # Register cleanup handler to remove lock file on exit
    def cleanup_lock():
        try:
            os.close(fd)
            if os.path.exists(lock_path):
                os.unlink(lock_path)
        except Exception:
            # Ignore cleanup errors (e.g., file already closed or deleted) to avoid issues during process exit
            pass

    atexit.register(cleanup_lock)
    return fd  # FD will be closed by cleanup_lock atexit handler
