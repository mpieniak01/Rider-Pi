"""Bounded latest-only RAM camera IPC. Reading never starts the producer."""

from __future__ import annotations

import contextlib
import hashlib
import json
import socket
import socketserver
import threading
import time

from services.camera_pipeline_store import runtime_path

MAX_FRAME_BYTES = 512 * 1024
MAX_HEADER_BYTES = 8192


class LatestFrames:
    def __init__(self):
        self.condition = threading.Condition()
        self.frames = {}
        self.preview_until = 0.0
        self.closed = False

    def publish(self, data, metadata, *, view="raw"):
        if not isinstance(data, bytes) or not 0 < len(data) <= MAX_FRAME_BYTES:
            raise ValueError("camera_pipeline_frame_size")
        row = dict(metadata, sha256=hashlib.sha256(data).hexdigest())
        with self.condition:
            if self.closed:
                return
            self.frames[view] = (data, row)
            self.condition.notify_all()

    def wanted(self, view):
        return view == "raw" or time.monotonic() < self.preview_until

    def get(self, *, after=None, timeout_ms=0, view="raw", metadata_only=False):
        with self.condition:
            if view == "proc" and not metadata_only:
                self.preview_until = time.monotonic() + 2.0
            self.condition.wait_for(
                lambda: self.closed or view in self.frames and self.frames[view][1]["frame_id"] != after,
                timeout_ms / 1000,
            )
            item = self.frames.get(view)
            if self.closed or item is None or item[1]["frame_id"] == after:
                return None
            data, metadata = item
            age = (time.monotonic_ns() - metadata["captured_monotonic_ns"]) / 1_000_000
            if not 0 <= age <= 3000:
                return None
            return (b"" if metadata_only else data), dict(metadata, frame_age_ms=age)

    def close(self):
        with self.condition:
            self.closed = True
            self.frames.clear()
            self.condition.notify_all()


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        if not self.server.slots.acquire(blocking=False):
            return
        try:
            self.connection.settimeout(2)
            encoded = self.rfile.readline(513)
            if len(encoded) > 512:
                return
            request = json.loads(encoded)
            if not isinstance(request, dict) or set(request) - {"after", "timeout_ms", "view", "metadata_only"}:
                return
            timeout = request.get("timeout_ms", 0)
            after = request.get("after")
            view = request.get("view", "raw")
            if (
                type(timeout) is not int
                or not 0 <= timeout <= 1000
                or view not in {"raw", "proc"}
                or after is not None
                and (not isinstance(after, str) or len(after) > 128)
                or type(request.get("metadata_only", False)) is not bool
            ):
                return
            item = self.server.frames.get(
                after=after, timeout_ms=timeout, view=view, metadata_only=request.get("metadata_only", False)
            )
            data, metadata = item if item is not None else (b"", None)
            header = json.dumps({"source": metadata, "length": len(data)}, allow_nan=False, separators=(",", ":"))
            self.wfile.write(header.encode() + b"\n")
            if data:
                self.wfile.write(data)
        except (OSError, ValueError, TypeError):
            return
        finally:
            self.server.slots.release()


class FrameServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, frames):
        self.path = runtime_path() / "latest.sock"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Never unlink a live producer's socket.
        if self.path.exists():
            with socket.socket(socket.AF_UNIX) as probe:
                try:
                    probe.connect(str(self.path))
                except OSError:
                    self.path.unlink()
                else:
                    raise RuntimeError("camera_pipeline_producer_already_running")
        self.frames, self.slots = frames, threading.BoundedSemaphore(12)
        super().__init__(str(self.path), _Handler)
        self.path.chmod(0o600)
        self.thread = threading.Thread(target=self.serve_forever, name="camera-ram-ipc", daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.frames.close()
        self.shutdown()
        self.server_close()
        self.thread.join(2)
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()


def read_frame(*, after=None, timeout_ms=0, view="raw", metadata_only=False):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(1.5 + timeout_ms / 1000)
        connection.connect(str(runtime_path() / "latest.sock"))
        connection.sendall(
            json.dumps(
                {"after": after, "timeout_ms": timeout_ms, "view": view, "metadata_only": metadata_only}
            ).encode()
            + b"\n"
        )
        with connection.makefile("rb") as stream:
            line = stream.readline(MAX_HEADER_BYTES + 1)
            if len(line) > MAX_HEADER_BYTES:
                raise ValueError("camera_pipeline_ipc_header_size")
            header = json.loads(line)
            length = header.get("length")
            if type(length) is not int or not 0 <= length <= MAX_FRAME_BYTES:
                raise ValueError("camera_pipeline_ipc_frame_size")
            metadata = header.get("source")
            if metadata is None:
                return None
            data = stream.read(length)
            if len(data) != length or not metadata_only and hashlib.sha256(data).hexdigest() != metadata["sha256"]:
                raise ValueError("camera_pipeline_ipc_frame_mismatch")
            return data, metadata
