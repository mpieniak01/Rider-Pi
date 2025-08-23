#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Idempotentny broker ZeroMQ (XPUB/XSUB) z PID-file i ładną obsługą zajętych portów.

ENV (opcjonalne):
  BUS_XPUB=tcp://127.0.0.1:5556
  BUS_XSUB=tcp://127.0.0.1:5555
  BUS_PIDFILE=/tmp/robot_broker.pid

Parametry:
  --xpub tcp://127.0.0.1:5556
  --xsub tcp://127.0.0.1:5555
  --pidfile /tmp/robot_broker.pid
  --status      # pokaż status i wyjdź
  --kill        # zabij działającego brokera i wyjdź
"""

import os, sys, signal, argparse, errno, atexit, time
import zmq

# --- bezpieczne printy (brak crasha przy ISO-8859-2) ---
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

def safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        s = " ".join(str(a) for a in args)
        sys.stdout.buffer.write((s + ("\n" if kwargs.get("end", "\n") == "\n" else "")).encode("utf-8", "replace"))
        sys.stdout.flush()

DEFAULT_XPUB = os.environ.get("BUS_XPUB", "tcp://127.0.0.1:5556")
DEFAULT_XSUB = os.environ.get("BUS_XSUB", "tcp://127.0.0.1:5555")
DEFAULT_PIDF = os.environ.get("BUS_PIDFILE", "/tmp/robot_broker.pid")

def pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    else:
        return True

def read_pid(pidfile: str):
    try:
        with open(pidfile, "r") as f:
            return int((f.read() or "").strip())
    except Exception:
        return None

def write_pid(pidfile: str):
    os.makedirs(os.path.dirname(pidfile), exist_ok=True)
    with open(pidfile, "w") as f:
        f.write(str(os.getpid()))

def remove_pid(pidfile: str):
    try:
        os.remove(pidfile)
    except FileNotFoundError:
        pass
    except Exception:
        pass

def main():
    ap = argparse.ArgumentParser(description="ZeroMQ broker XPUB/XSUB (idempotentny)")
    ap.add_argument("--xpub", default=DEFAULT_XPUB, help="adres XPUB bind")
    ap.add_argument("--xsub", default=DEFAULT_XSUB, help="adres XSUB bind")
    ap.add_argument("--pidfile", default=DEFAULT_PIDF, help="ścieżka PID-file")
    ap.add_argument("--status", action="store_true", help="pokaż status i wyjdź")
    ap.add_argument("--kill", action="store_true", help="zatrzymaj działającego brokera i wyjdź")
    args = ap.parse_args()

    pid = read_pid(args.pidfile)
    if args.status:
        if pid and pid_is_running(pid):
            safe_print(f"[broker] running (PID {pid}) XPUB={args.xpub} XSUB={args.xsub}")
        else:
            safe_print("[broker] not running")
        return 0

    if args.kill:
        if pid and pid_is_running(pid):
            os.kill(pid, signal.SIGTERM)
            safe_print(f"[broker] sent SIGTERM to PID {pid}")
            for _ in range(30):
                if not pid_is_running(pid):
                    break
                time.sleep(0.1)
            remove_pid(args.pidfile)
        else:
            safe_print("[broker] nothing to kill")
        return 0

    # jeśli jest PID-file i proces żyje -> już działa
    if pid and pid_is_running(pid):
        safe_print(f"[broker] already running (PID {pid}) XPUB={args.xpub} XSUB={args.xsub}")
        return 0
    else:
        # sprzątnij stary PID-file (stale)
        if pid:
            remove_pid(args.pidfile)

    ctx = zmq.Context.instance()
    xpub = ctx.socket(zmq.XPUB)
    xsub = ctx.socket(zmq.XSUB)

    for s in (xpub, xsub):
        s.setsockopt(zmq.SNDHWM, 1000)
        s.setsockopt(zmq.RCVHWM, 1000)
        s.setsockopt(zmq.LINGER, 0)

    try:
        xpub.bind(args.xpub)
        xsub.bind(args.xsub)
    except zmq.ZMQError as e:
        if e.errno == errno.EADDRINUSE:
            safe_print(f"[broker] ports busy ({args.xpub}, {args.xsub}) - assuming broker is running. Exit 0.")
            try: xpub.close(0)
            except Exception: pass
            try: xsub.close(0)
            except Exception: pass
            try: ctx.term()
            except Exception: pass
            return 0
        raise

    write_pid(args.pidfile)
    atexit.register(remove_pid, args.pidfile)

    stop = False
    def _sig(sig, frm):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    safe_print(f"[broker] running XPUB={args.xpub} XSUB={args.xsub} PID={os.getpid()}")

    try:
        zmq.proxy(xsub, xpub)
    except KeyboardInterrupt:
        pass
    finally:
        try: xpub.close(0)
        except Exception: pass
        try: xsub.close(0)
        except Exception: pass
        try: ctx.term()
        except Exception: pass
        remove_pid(args.pidfile)
        safe_print("[broker] bye")

if __name__ == "__main__":
    sys.exit(main())
