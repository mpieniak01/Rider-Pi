"""Real loopback HTTP candidate rejection crosses native reference transport."""

from __future__ import annotations

import contextlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from apps.camera import pipeline_ipc, pipeline_runtime
from apps.compute import navigation, runners
from services import camera_pipeline_store as store
from services.navigation_config import DEFAULT


@pytest.fixture
def environment(monkeypatch, tmp_path):
    monkeypatch.setenv("RIDER_CAMERA_PIPELINE_CONFIG", str(tmp_path / "camera.json"))
    monkeypatch.setenv("RIDER_CAMERA_PIPELINE_RUNTIME", str(tmp_path / "runtime"))
    monkeypatch.setenv("RIDER_NAVIGATION_STATUS", str(tmp_path / "navigation.json"))
    monkeypatch.setenv("PREVIEW_ROT", "0")
    store.write(
        {"contract_version": 1, "revision": 4, "profile": dict(store.DEFAULT_PROFILE, remote_transport="mjpeg")}
    )
    producer = pipeline_runtime.CameraProducer(store.snapshot())
    producer.encoded(b"jpeg-source", time.monotonic_ns(), (320, 240))
    server = pipeline_ipc.FrameServer(producer.frames)
    server.start()
    commands = []
    monkeypatch.setattr(navigation, "submit_control", lambda body, **_: (commands.append(body) or {"ok": True}, 200))
    monkeypatch.setattr(navigation, "BusPub", lambda **_: pytest.fail("physical actuator BUS opened"))

    class Source:
        def __init__(self):
            self.reader = runners.FrameSource(require_bytes=False)

        def recv(self, timeout):
            # Each capture is new, as on the running native hardware producer.
            producer.encoded(b"jpeg-source", time.monotonic_ns(), (320, 240))
            return self.reader.recv(timeout)

        def close(self):
            self.reader.close()

    try:
        yield producer, Source, commands
    finally:
        server.close()


@contextlib.contextmanager
def endpoint(producer, status, code):
    requests = []
    runtime = SimpleNamespace(runner=None)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, status, body):
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            self.send(200, {"stream": {"ready": True, "latest_source": producer.frames.get(metadata_only=True)[1]}})

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, payload, json.loads(self.headers["X-Rider-Vision"])))
            if len(requests) == 1:
                self.send(status, {"detail": {"code": code}})
                return
            frame = payload["frame"]
            self.send(
                200,
                {
                    **{
                        key: frame[key]
                        for key in ("protocol_version", "run_id", "frame_id", "sequence", "config_revision")
                    },
                    "source": payload["source"],
                    "state": "clear",
                    "action": "stop",
                    "reason": "observe_only",
                    "valid_for_ms": 0,
                    "clear_count": 1,
                },
            )
            runtime.runner.closed.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port), requests, runtime
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


@pytest.mark.parametrize("status,code", [(409, "vision_frame_expired"), (429, "vision_run_rate_limited")])
def test_observe_discards_rejected_reference_and_analyzes_next_capture(environment, monkeypatch, status, code):
    producer, source, commands = environment
    policy = dict(DEFAULT)
    monkeypatch.setattr(navigation.navigation_config, "snapshot", lambda: dict(policy))
    with endpoint(producer, status, code) as (url, requests, runtime):
        selection = {"id": "venom", "url": url, "device_id": "pi", "token": "fixture-private"}
        monkeypatch.setattr(navigation, "selected_executor", lambda: dict(selection))
        runner = navigation.NavigationRunner(observe_only=True, source_factory=source)
        runtime.runner = runner
        rows, record = [], runner._status

        def capture_status(decision):
            if decision:
                rows.append(json.loads(json.dumps(decision)))
            record(decision)

        monkeypatch.setattr(runner, "_status", capture_status)
        assert runner.run() == 0
    assert commands == []
    assert len(requests) == 2
    assert all(path.endswith("/vision/decision-reference") for path, _, _ in requests)
    first, second = (body for _, body, _ in requests)
    assert first["source"]["frame_id"] != second["source"]["frame_id"]
    assert second["source"]["sequence"] > first["source"]["sequence"]
    assert [body["frame"]["sequence"] for body in (first, second)] == [1, 2]
    assert first["source"]["sequence"] != first["frame"]["sequence"]
    assert all(body["frame"] == meta for (_, body, meta) in requests)
    assert all(len(body["frame"]["frame_id"]) == 64 for body in (first, second))
    assert all(body["frame"]["frame_id"] != body["source"]["frame_id"] for body in (first, second))
    rejected = next(row for row in rows if row["sequence"] == 1)
    assert rejected["state"] == "unknown"
    assert rejected["action"] == rejected["vision_action"] == "stop"
    assert rejected["valid_for_ms"] == 0
    assert rejected["clear_count"] == 0
    assert rejected["source"] == first["source"]
    assert rejected["frame_id"] == first["frame"]["frame_id"]
    assert rejected["http_status"] == status
    assert rejected["transport_error"] == rejected["reason"] == code
    assert runner.last_result["source"] == second["source"]


@pytest.mark.parametrize("status,code", [(409, "vision_frame_expired"), (429, "vision_run_rate_limited")])
def test_active_drive_rejection_latches_in_real_reference_path(environment, monkeypatch, status, code):
    producer, source, commands = environment
    policy = dict(DEFAULT, mode="drive", verified=True, calibration_id="fixture", model_sha256="a" * 64)
    monkeypatch.setattr(navigation.navigation_config, "snapshot", lambda: dict(policy))
    monkeypatch.setattr(navigation, "read_status", lambda: {"owner": "navigation", "generation": "fixture"})
    with endpoint(producer, status, code) as (url, requests, runtime):
        selection = {"id": "venom", "url": url, "device_id": "pi", "token": "fixture-private"}
        monkeypatch.setattr(navigation, "selected_executor", lambda: dict(selection))
        runner = navigation.NavigationRunner(
            source_factory=source, publisher_factory=lambda: SimpleNamespace(close=lambda: None)
        )
        runtime.runner = runner
        runner.motion_started = True
        runner.generation = "fixture"
        monkeypatch.setattr(runner, "_authority", lambda: True)
        assert runner.run() == 2
    assert len(requests) == 1
    assert runner.lease.latched
    assert runner.lease.reason == "navigation_" + code
    assert commands
    assert all(command["action"] == "stop" for command in commands)


def test_observe_still_latches_when_source_epoch_changes(environment, monkeypatch):
    producer, source, commands = environment
    monkeypatch.setattr(navigation.navigation_config, "snapshot", lambda: dict(DEFAULT))
    with endpoint(producer, 409, "stream_epoch_changed") as (url, requests, runtime):
        selection = {"id": "venom", "url": url, "device_id": "pi", "token": "fixture-private"}
        monkeypatch.setattr(navigation, "selected_executor", lambda: dict(selection))
        runner = navigation.NavigationRunner(observe_only=True, source_factory=source)
        runtime.runner = runner
        assert runner.run() == 2
    assert len(requests) == 1
    assert runner.lease.latched
    assert runner.lease.reason == "navigation_stream_epoch_changed"
    assert commands == []
