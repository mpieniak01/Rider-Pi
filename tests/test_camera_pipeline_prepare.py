"""Replay cold native S15 startup with real RAM IPC; never open motors or cameras."""

from __future__ import annotations

import io
import json
import time
import urllib.error
from types import SimpleNamespace

import pytest

from apps.camera import pipeline_ipc, pipeline_runtime
from apps.compute import navigation, stream_prepare
from services import camera_pipeline_store as store
from services.navigation_config import DEFAULT


class Response:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read(self, limit):
        return self.body[:limit]


@pytest.fixture
def environment(monkeypatch, tmp_path):
    monkeypatch.setenv("RIDER_CAMERA_PIPELINE_CONFIG", str(tmp_path / "camera.json"))
    monkeypatch.setenv("RIDER_CAMERA_PIPELINE_RUNTIME", str(tmp_path / "runtime"))
    monkeypatch.setenv("RIDER_NAVIGATION_STATUS", str(tmp_path / "navigation.json"))
    monkeypatch.setenv("PREVIEW_ROT", "0")
    profile = dict(store.DEFAULT_PROFILE, remote_transport="mjpeg")
    store.write({"contract_version": 1, "revision": 4, "profile": profile})
    producer = pipeline_runtime.CameraProducer(store.snapshot())
    server = pipeline_ipc.FrameServer(producer.frames)
    server.start()
    selection = {"id": "venom", "url": "http://127.0.0.1:8800", "device_id": "pi", "token": "private-test-token"}
    monkeypatch.setattr(navigation.navigation_config, "snapshot", lambda: dict(DEFAULT))
    monkeypatch.setattr(navigation, "selected_executor", lambda: dict(selection))
    monkeypatch.setattr(navigation, "submit_control", lambda *_args, **_kwargs: pytest.fail("observation actuated"))
    monkeypatch.setattr(navigation, "BusPub", lambda **_: pytest.fail("observation opened actuator BUS"))
    try:
        yield producer, selection, tmp_path
    finally:
        server.close()


def publish(producer):
    producer.encoded(b"jpeg-source", time.monotonic_ns(), (320, 240))
    return producer.frames.get(metadata_only=True)[1]


def test_cold_s15_waits_for_first_native_ram_frame_then_completes_reference_cycle(environment, monkeypatch):
    producer, selection, _ = environment
    now, calls, decisions = [0.0], [], []
    prepare = stream_prepare.prepare_stream

    def sleep(delay):
        now[0] += delay
        if now[0] >= 1 and not producer.frames.frames:
            publish(producer)

    def warmup(req, timeout):
        calls.append((now[0], req, timeout))
        assert now[0] >= 1
        source = producer.frames.get(metadata_only=True)[1]
        return Response({"stream": {"ready": True, "latest_source": source}})

    monkeypatch.setattr(
        stream_prepare,
        "prepare_stream",
        lambda **kwargs: prepare(opener=SimpleNamespace(open=warmup), clock=lambda: now[0], sleep=sleep, **kwargs),
    )

    def decision(frame, reference, content_type):
        decisions.append((frame, reference, content_type))
        runner.closed.set()
        return {"state": "clear", "action": "stop", "reason": "observe_only"}

    runner = navigation.NavigationRunner(observe_only=True, request=decision)
    assert runner.run() == 0
    assert len(calls) == len(decisions) == 1
    assert calls[0][1].full_url.endswith("/vision/status?stream=true")
    frame, reference, content_type = decisions[0]
    assert content_type == "application/json" and frame["age_ms"] < frame["deadline_ms"]
    assert reference["camera_session"] == producer.session
    assert reference["transport_epoch"] == producer.epoch and reference["pipeline_revision"] == 4
    assert runner.motion_publisher is None and runner.intent is None


def test_no_native_frame_times_out_within_same_prepare_budget_without_calling_host(environment):
    _, selection, _ = environment
    now = [0.0]
    opener = SimpleNamespace(open=lambda *_args, **_kwargs: pytest.fail("host called before first RAM frame"))
    with pytest.raises(navigation.ComputeError, match="navigation_stream_prepare_timeout"):
        stream_prepare.prepare_stream(
            selection=selection,
            opener=opener,
            timeout_s=2,
            clock=lambda: now[0],
            sleep=lambda delay: now.__setitem__(0, now[0] + delay),
        )
    assert now[0] == pytest.approx(2)


def test_old_host_session_is_not_accepted_as_preparation_for_new_camera(environment):
    producer, selection, _ = environment
    source = dict(publish(producer), camera_session="previous-session")
    opener = SimpleNamespace(
        open=lambda *_args, **_kwargs: Response({"stream": {"ready": True, "latest_source": source}})
    )
    with pytest.raises(navigation.ComputeError, match="navigation_stream_source_mismatch"):
        stream_prepare.prepare_stream(selection=selection, opener=opener)


def test_failed_warmup_preserves_domain_code_in_runner_status_and_log_without_blind_retry(
    environment, monkeypatch, caplog
):
    producer, _, root = environment
    publish(producer)
    calls = []

    def warmup(*_args, **_kwargs):
        calls.append(True)
        raise urllib.error.HTTPError(
            "http://private-host/path",
            503,
            "do-not-log-private-test-token",
            {},
            io.BytesIO(b'{"detail":{"code":"stream_unavailable","details":{"token":"private-test-token"}}}'),
        )

    monkeypatch.setattr(stream_prepare.urllib.request, "build_opener", lambda *_: SimpleNamespace(open=warmup))
    runner = navigation.NavigationRunner(observe_only=True)
    assert runner.run() == 2 and calls == [True]
    expected = "navigation_stream_prepare_stream_unavailable"
    assert runner.lease.reason == expected and expected in caplog.text
    assert "http_status=503" in caplog.text
    assert "private-test-token" not in caplog.text and "private-host" not in caplog.text
    status = json.loads((root / "navigation.json").read_text())
    assert status["stop_reason"] == expected and status["running"] is False


@pytest.mark.parametrize("value", ["https://host/private?token=secret", "not a code", "x" * 100, None])
def test_http_diagnostic_rejects_response_text_instead_of_logging_it(value):
    error = urllib.error.HTTPError(
        "http://private",
        503,
        "secret",
        {},
        io.BytesIO(json.dumps({"detail": {"code": value}}).encode()),
    )
    assert stream_prepare.http_error_code(error) == "http_503"
    # A later logger sees the same code even though the bounded body was consumed.
    assert stream_prepare.http_error_code(error) == "http_503"


def test_ready_response_after_prepare_deadline_is_not_accepted(environment):
    producer, selection, _ = environment
    source = publish(producer)
    now = [0.0]

    def late_reply(*_args, **_kwargs):
        now[0] = 2.1
        return Response({"stream": {"ready": True, "latest_source": source}})

    with pytest.raises(navigation.ComputeError, match="navigation_stream_prepare_timeout"):
        stream_prepare.prepare_stream(
            selection=selection, opener=SimpleNamespace(open=late_reply), clock=lambda: now[0]
        )


@pytest.mark.parametrize("invalid", ["stale", "revision"])
def test_local_stale_or_foreign_revision_cannot_begin_host_prepare(environment, invalid):
    producer, selection, _ = environment
    source = publish(producer)
    source["captured_monotonic_ns"] = time.monotonic_ns() - 500_000_000 if invalid == "stale" else time.monotonic_ns()
    if invalid == "revision":
        source["pipeline_revision"] -= 1
    producer.frames.publish(b"jpeg-source", source)
    now = [0.0]
    with pytest.raises(navigation.ComputeError, match="navigation_stream_prepare_timeout"):
        stream_prepare.prepare_stream(
            selection=selection,
            opener=SimpleNamespace(open=lambda *_args, **_kwargs: pytest.fail("invalid local source reached host")),
            timeout_s=0.1,
            clock=lambda: now[0],
            sleep=lambda delay: now.__setitem__(0, now[0] + delay),
        )
