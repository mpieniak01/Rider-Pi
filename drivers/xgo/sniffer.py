"""Optional in-process UART tap. Never opens a UART or sends device commands."""

from __future__ import annotations

import json
import os
import queue
import select
import socket
import threading
import time
from pathlib import Path


def runtime_directory():
    path = Path(f"/tmp/rider-uart-sniffer-{os.getuid()}")
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if path.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PermissionError("sniffer_runtime_permissions")
    return path


class Capture:
    """One background writer; bounded nonblocking producers; local control socket."""

    def __init__(self):
        self.events = queue.Queue(maxsize=1024)
        self.active = False
        self.session = 0
        self.closed = False
        self.dropped = 0
        self.error = None
        self.output = None
        self.bytes = 0
        self.deadline = 0
        self.limit = 0
        self.stream = None
        self.path = runtime_directory() / f"{os.getpid()}.sock"
        self.control = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            self.control.bind(str(self.path))
            os.chmod(self.path, 0o600)
        except Exception:
            self.control.close()
            raise
        self.thread = threading.Thread(target=self._run, name="uart-sniffer", daemon=True)
        self.thread.start()

    def record(self, direction, data=b"", **extra):
        if not self.active:
            return
        try:
            raw = bytes(data)
            item = {
                "time_ns": time.monotonic_ns(),
                "direction": direction,
                "session": self.session,
                "hex": raw[:4096].hex(),
                "truncated": len(raw) > 4096,
                **extra,
            }
            self.events.put_nowait(item)
        except Exception:
            self.dropped += 1

    def status(self):
        return {
            "pid": os.getpid(),
            "active": self.active,
            "file": self.output,
            "bytes": self.bytes,
            "dropped": self.dropped,
            "error": self.error,
            "remaining_s": max(0, round(self.deadline - time.monotonic(), 1)) if self.active else 0,
        }

    def _line(self, row, force=False):
        data = json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n"
        size = len(data.encode())
        if not force and self.bytes + size > self.limit - 1024:
            self._stop("size_limit")
            return
        self.stream.write(data)
        self.bytes += size

    def _stop(self, reason):
        self.active = False
        # No old-session events can leak into a later recording.
        while True:
            try:
                self.events.get_nowait()
                self.dropped += 1
            except queue.Empty:
                break
        if self.stream:
            try:
                self._line(
                    {"event": "end", "reason": reason, "dropped": self.dropped, "time_ns": time.monotonic_ns()},
                    force=True,
                )
                self.stream.close()
            finally:
                self.stream = None

    def _command(self, command):
        action = command.get("action")
        if action == "attach":
            seconds = command.get("seconds", 60)
            limit = command.get("max_bytes", 8 * 1024 * 1024)
            if type(seconds) is not int or not 1 <= seconds <= 300:
                raise ValueError("seconds_must_be_1_to_300")
            if type(limit) is not int or not 4096 <= limit <= 8 * 1024 * 1024:
                raise ValueError("max_bytes_must_be_4096_to_8388608")
            if self.active:
                raise ValueError("already_attached")
            self.output = str(runtime_directory() / f"capture-{os.getpid()}-{time.time_ns()}.jsonl")
            fd = os.open(self.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            self.stream = os.fdopen(fd, "w", buffering=1)
            self.bytes = self.dropped = 0
            self.error = None
            self.limit = limit
            self.deadline = time.monotonic() + seconds
            self._line(
                {
                    "event": "start",
                    "pid": os.getpid(),
                    "wall_time_ns": time.time_ns(),
                    "time_ns": time.monotonic_ns(),
                    "scope": "serial_calls_not_wire",
                    "flush_discard_is_unobservable": True,
                }
            )
            self.session += 1
            self.active = True
        elif action == "detach":
            self._stop("operator_detach")
        elif action != "status":
            raise ValueError("unknown_action")
        return self.status()

    def _respond_control(self):
        data, address = self.control.recvfrom(4096)
        try:
            response = self._command(json.loads(data))
        except Exception as exc:
            response = {"command_error": str(exc)}
        try:
            self.control.sendto(json.dumps(response).encode(), address)
        except OSError:
            pass

    def _drain_capture_events(self):
        for _ in range(128):
            try:
                item = self.events.get_nowait()
            except queue.Empty:
                break
            if self.active and item["session"] == self.session:
                self._line(item)

    def _run(self):
        while not self.closed:
            try:
                readable, _, _ = select.select([self.control], [], [], 0.05 if self.active else 1.0)
                if readable:
                    self._respond_control()
                if self.active and time.monotonic() >= self.deadline:
                    self._stop("time_limit")
                self._drain_capture_events()
            except Exception as exc:
                self.error = type(exc).__name__
                try:
                    self._stop("capture_error")
                except Exception:
                    self.active = False
        try:
            self._stop("process_close")
        finally:
            self.control.close()
            self.path.unlink(missing_ok=True)

    def close(self):
        self.active = False
        self.closed = True
        try:
            self.control.sendto(b"{}", str(self.path))
        except OSError:
            pass
        self.thread.join(timeout=0.2)


class SerialTap:
    """Transparent wrapper; only observes reads/writes the owner already performs."""

    def __init__(self, serial, capture):
        object.__setattr__(self, "_serial", serial)
        object.__setattr__(self, "_capture", capture)

    def __getattr__(self, name):
        return getattr(self._serial, name)

    def __setattr__(self, name, value):
        setattr(self._serial, name, value)

    def _observe(self, *args, **kwargs):
        try:
            self._capture.record(*args, **kwargs)
        except Exception:
            pass

    def write(self, data):
        try:
            result = self._serial.write(data)
        except Exception as exc:
            self._observe("fault", operation="write", error=type(exc).__name__)
            raise
        # Record only the bytes accepted by the serial implementation.
        self._observe(
            "tx",
            data if result is None else data[:result],
            accepted=result,
            completion="unknown" if result is None else "serial_write",
        )
        return result

    def read(self, size=1):
        try:
            data = self._serial.read(size)
        except Exception as exc:
            self._observe("fault", operation="read", error=type(exc).__name__)
            raise
        self._observe("rx", data)
        return data

    def flushInput(self):
        result = self._serial.flushInput()
        self._observe("gap", cause="flushInput", discarded_bytes="unknown")
        return result

    def reset_input_buffer(self):
        result = self._serial.reset_input_buffer()
        self._observe("gap", cause="reset_input_buffer", discarded_bytes="unknown")
        return result

    def close(self):
        try:
            self._capture.close()
        except Exception:
            pass
        return self._serial.close()


def install(serial):
    """Opt-in tap; disabled mode preserves the native transport with no worker."""
    if os.getenv("RIDER_UART_SNIFFER_ENABLED", "0") != "1":
        return serial
    try:
        return SerialTap(serial, Capture())
    except Exception:
        return serial
