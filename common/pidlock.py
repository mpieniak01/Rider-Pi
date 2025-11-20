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

    # Register cleanup handler to remove lock file on normal exit
    # Note: atexit handlers won't run on SIGKILL (kill -9), so lock file will remain in that case
    def _cleanup():
        try:
            os.close(fd)
        except Exception:
            # Ignore errors when closing fd during cleanup; process is exiting anyway.
            pass
        try:
            if os.path.exists(lock_path):
                os.unlink(lock_path)
        except Exception:
            # Ignore errors during lock file removal; process is exiting and lock will be overwritten next run.
            pass

    atexit.register(_cleanup)
    return fd  # nie zamykaj; trzyma lock do końca procesu
