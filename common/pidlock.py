import os, sys, fcntl

def single_instance(lock_path="/tmp/rider-motion.lock"):
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.write(fd, str(os.getpid()).encode())
    except OSError:
        print(f"[PIDLOCK] another instance running (lock: {lock_path})", file=sys.stderr)
        sys.exit(1)
    return fd  # nie zamykaj; trzyma lock do końca procesu
