"""Stream handshake/reference regressions with in-memory producers and HTTP fakes."""

from __future__ import annotations

import hashlib
import json
import sys
import time
from types import SimpleNamespace

import numpy as np
import pytest

from apps.camera import pipeline_native, pipeline_runtime
from apps.compute import navigation, runners, stream_prepare
from services import camera_pipeline_store as store


@pytest.fixture(autouse=True)
def paths(monkeypatch, tmp_path):
    monkeypatch.setenv("RIDER_CAMERA_PIPELINE_CONFIG", str(tmp_path / "camera.json"))
    monkeypatch.setenv("RIDER_CAMERA_PIPELINE_RUNTIME", str(tmp_path / "runtime"))
    monkeypatch.setenv("PREVIEW_ROT", "0")
    monkeypatch.setenv("SNAP_DIR", str(tmp_path / "snapshots"))
    store.write(
        {"contract_version": 1, "revision": 1, "profile": dict(store.DEFAULT_PROFILE, remote_transport="mjpeg")}
    )


def source():
    return {
        "contract_version": 1,
        "camera_session": "camera-1",
        "sequence": 1,
        "transport_epoch": 1,
        "pipeline_revision": 1,
        "frame_id": "camera-1-1",
        "sha256": hashlib.sha256(b"jpeg").hexdigest(),
        "frame_age_ms": 1,
        "captured_monotonic_ns": time.monotonic_ns(),
        "encoded_width": 320,
        "encoded_height": 240,
        "image_transform": {"rotation": 270, "flip_h": False, "flip_v": False},
    }


def test_navigation_metadata_and_explicit_s12_bytes_share_one_ram_producer(monkeypatch):
    from apps.camera import pipeline_ipc

    calls, metadata = [], source()

    def read(**kwargs):
        calls.append(kwargs)
        return (b"" if kwargs["metadata_only"] else b"jpeg"), metadata

    monkeypatch.setattr(pipeline_ipc, "read_frame", read)
    nav_source, scene_source = runners.FrameSource(require_bytes=False), runners.FrameSource()
    nav_frame, scene_frame = nav_source.recv(50), scene_source.recv(50)
    assert isinstance(nav_frame["data"], dict) and nav_frame["content_type"] == "application/json"
    assert nav_frame["data"] == {
        k: metadata[k]
        for k in ("camera_session", "sequence", "transport_epoch", "pipeline_revision", "frame_id", "sha256")
    }
    assert scene_frame["data"] == b"jpeg" and scene_frame["content_type"] == "image/jpeg"
    assert [row["metadata_only"] for row in calls] == [True, False]
    assert nav_frame["captured_monotonic_ns"] == metadata["captured_monotonic_ns"]
    nav_source.close()
    scene_source.close()


class Response:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self.body[:limit]


def selection():
    return {"url": "http://127.0.0.1:9999", "device_id": "fixture-pi", "token": "fixture-private"}


def test_prepare_waits_for_real_ingest_without_motion_or_model_calls():
    calls = []
    responses = [
        {"stream": {"ready": False}},
        {"stream": {"ready": True, "latest_source": source()}},
    ]
    opener = SimpleNamespace(open=lambda req, timeout: calls.append((req, timeout)) or Response(responses.pop(0)))
    clock = [10.0]
    prepared = stream_prepare.prepare_stream(
        selection=selection(),
        opener=opener,
        clock=lambda: clock[0],
        sleep=lambda delay: clock.__setitem__(0, clock[0] + delay),
    )
    assert prepared["ready"] is True
    assert len(calls) == 2
    assert all(call[0].full_url.endswith("/vision/status?stream=true") for call in calls)
    assert all(call[0].get_method() == "GET" for call in calls)


def test_prepare_timeout_does_not_synthesize_a_clear_verdict():
    clock = [0.0]
    opener = SimpleNamespace(open=lambda *_args, **_kw: Response({"stream": {"ready": False}}))
    with pytest.raises(navigation.ComputeError, match="navigation_stream_prepare_timeout"):
        stream_prepare.prepare_stream(
            selection=selection(),
            opener=opener,
            timeout_s=0.1,
            clock=lambda: clock[0],
            sleep=lambda delay: clock.__setitem__(0, clock[0] + delay),
        )


def test_reference_request_sends_no_jpeg_and_requires_exact_source_echo(monkeypatch):
    runner = navigation.NavigationRunner.__new__(navigation.NavigationRunner)
    runner.selection, runner.policy = selection(), {"decision_budget_ms": 300, "mode": "observe"}
    reference = {
        k: source()[k]
        for k in ("camera_session", "sequence", "transport_epoch", "pipeline_revision", "frame_id", "sha256")
    }
    received = []

    def request(req, timeout):
        received.append((req, timeout))
        return Response({"source": dict(reference), "action": "stop"})

    monkeypatch.setattr(navigation.urllib.request, "build_opener", lambda *_: SimpleNamespace(open=request))
    meta = {"frame_id": "decision-1", "sequence": 1}
    assert runner._request(meta, reference, "application/json")["action"] == "stop"
    req, _ = received[0]
    assert req.full_url.endswith("/vision/decision-reference")
    assert json.loads(req.data) == {"frame": meta, "source": reference}
    assert b"jpeg" not in req.data
    monkeypatch.setattr(
        navigation.urllib.request,
        "build_opener",
        lambda *_: SimpleNamespace(open=lambda *_a, **_k: Response({"source": dict(reference, sequence=2)})),
    )
    with pytest.raises(navigation.ComputeError, match="navigation_reference_mismatch"):
        runner._request(meta, reference, "application/json")


def test_snapshot_request_preserves_binary_endpoint(monkeypatch):
    runner = navigation.NavigationRunner.__new__(navigation.NavigationRunner)
    runner.selection, runner.policy = selection(), {"decision_budget_ms": 300, "mode": "observe"}
    calls = []
    monkeypatch.setattr(
        navigation.urllib.request,
        "build_opener",
        lambda *_: SimpleNamespace(open=lambda req, **kw: calls.append(req) or Response({"action": "stop"})),
    )
    runner._request({"frame_id": "fixture"}, b"jpeg", "image/jpeg")
    assert calls[0].data == b"jpeg" and calls[0].full_url.endswith("/vision/decision")


def test_hardware_adapter_has_one_yuv_capture_and_closes_idempotently(monkeypatch):
    calls, received = [], []
    captured = time.monotonic_ns() - 1_000_000

    class Encoder:
        def _encode(self, stream, request):
            self.output.outputframe(b"hardware-jpeg", timestamp=0)

    class Output:
        recording = True

    class Camera:
        def create_video_configuration(self, **kwargs):
            calls.append(("configuration", kwargs))
            return kwargs

        def configure(self, config):
            pass

        def start_recording(self, encoder, sink, **kwargs):
            encoder.output = sink
            fake = SimpleNamespace(
                request=SimpleNamespace(buffers={"main": SimpleNamespace(metadata=SimpleNamespace(timestamp=captured))})
            )
            encoder._encode("main", fake)

        def stop_recording(self):
            calls.append(("stop",))

        def close(self):
            calls.append(("close",))

    monkeypatch.setitem(sys.modules, "picamera2", SimpleNamespace(Picamera2=Camera))
    monkeypatch.setitem(
        sys.modules, "picamera2.encoders", SimpleNamespace(MJPEGEncoder=Encoder, Quality=SimpleNamespace(HIGH=1))
    )
    monkeypatch.setitem(sys.modules, "picamera2.outputs", SimpleNamespace(Output=Output))
    camera = pipeline_native.NativeCamera(lambda *args: received.append(args))
    camera.close()
    camera.close()
    assert received == [(b"hardware-jpeg", captured, (320, 240))]
    assert calls[0][1]["main"] == {"size": (320, 240), "format": "YUV420"}
    assert calls[-2:] == [("stop",), ("close",)]


def test_runtime_failure_stays_failed_and_releases_camera(monkeypatch):
    store.write({"contract_version": 1, "revision": 1, "profile": dict(store.DEFAULT_PROFILE)})
    from apps.camera import utils

    calls = []
    import zmq

    publisher = SimpleNamespace(setsockopt=lambda *_: None, bind=lambda *_: None, close=lambda **_: None)
    monkeypatch.setattr(zmq, "Context", SimpleNamespace(instance=lambda: SimpleNamespace(socket=lambda *_: publisher)))

    class BrokenCamera:
        def __call__(self):
            raise RuntimeError("fixture_capture_failed")

        def close(self):
            calls.append("closed")

    from common import bus

    monkeypatch.setattr(bus, "BusPub", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(utils, "open_camera", lambda _: (BrokenCamera(), (320, 240)))
    assert pipeline_runtime.main() == 1
    status = json.loads((store.runtime_path() / "status.json").read_text())
    assert status["state"] == "failed" and status["error"] == "fixture_capture_failed"
    assert calls == ["closed"] and not (store.runtime_path() / "latest.sock").exists()


def test_local_preview_is_encoded_only_on_explicit_proc_demand(monkeypatch):
    store.write(
        {"contract_version": 1, "revision": 1, "profile": dict(store.DEFAULT_PROFILE, analysis_location="local")}
    )
    producer = pipeline_runtime.CameraProducer(store.snapshot())
    frame = np.zeros((40, 60, 3), dtype=np.uint8)
    producer.array(frame, time.monotonic_ns())
    assert "proc" not in producer.frames.frames
    producer.frames.get(view="proc")
    producer.array(frame, time.monotonic_ns())
    assert producer.frames.get(view="proc")[0].startswith(b"\xff\xd8\xff")
    assert not (store.runtime_path().parent / "snapshots" / "proc.jpg").exists()


@pytest.mark.parametrize(
    "change,expected_sequence",
    [
        ({}, 1),
        ({"camera_session": "other"}, 2),
        ({"transport_epoch": 9}, 2),
        ({"pipeline_revision": 9}, 2),
        ({"captured_monotonic_ns": 1}, 2),
    ],
)
def test_first_reference_only_uses_ingested_source_with_matching_live_pi_epoch(monkeypatch, change, expected_sequence):
    from apps.camera import pipeline_ipc

    initial = dict(source(), **change)
    current = dict(source(), sequence=2, frame_id="camera-1-2")
    monkeypatch.setattr(pipeline_ipc, "read_frame", lambda **_: (b"", current))
    client = runners.FrameSource(require_bytes=False, initial_source=initial)
    frame = client.recv(0)
    assert frame["data"]["sequence"] == expected_sequence
    assert frame["captured_monotonic_ns"] == (initial if expected_sequence == 1 else current)["captured_monotonic_ns"]


def test_new_profile_disables_legacy_distributor_and_local_rejects_remote_goals():
    from common.service_catalog import DEFAULT_REGISTRY, task_availability, task_units

    units = task_units(DEFAULT_REGISTRY["s2_camera_preview"])
    assert "camera-capture@raw.service" in units and "frame-distributor.service" not in units
    store.write(
        {"contract_version": 1, "revision": 2, "profile": dict(store.DEFAULT_PROFILE, analysis_location="local")}
    )
    for goal in ("s14_venom_navigation", "s15_venom_perception", "s12_venom_vision"):
        availability = task_availability(DEFAULT_REGISTRY[goal])
        assert not availability["start_available"]
        assert availability["start_unavailable_reason"] == "camera_pipeline_local_analysis_selected"


def test_missing_profile_preserves_legacy_units():
    from common.service_catalog import DEFAULT_REGISTRY, task_units

    store.config_path().unlink()
    units = task_units(DEFAULT_REGISTRY["s2_camera_preview"])
    assert "camera-capture@raw.service" in units and "frame-distributor.service" in units


def test_stale_missing_reference_retry_is_bounded_to_initial_or_observe_phase():
    import io
    import urllib.error

    runner = navigation.NavigationRunner.__new__(navigation.NavigationRunner)
    runner.policy = {"mode": "drive"}
    runner.motion_started, runner.startup_deadline, runner.clock = False, 5.0, lambda: 0.0

    def error(code):
        return urllib.error.HTTPError(
            "http://fixture", 409, "conflict", {}, io.BytesIO(json.dumps({"detail": {"code": code}}).encode())
        )

    assert runner._retry_observation(error("stream_frame_unavailable"))
    assert not runner._retry_observation(error("stream_epoch_changed"))
    runner.motion_started = True
    assert not runner._retry_observation(error("stream_frame_unavailable"))


def test_metadata_status_does_not_enable_proc_encode():
    from apps.camera.pipeline_ipc import LatestFrames

    frames = LatestFrames()
    assert frames.get(view="proc", metadata_only=True) is None
    assert not frames.wanted("proc")


def test_ram_legacy_description_never_stats_abandoned_raw_file(monkeypatch):
    from apps.camera import pipeline_ipc
    from services.api_core import frames

    metadata = source()
    metadata["frame_age_ms"] = 20
    monkeypatch.setattr(pipeline_ipc, "read_frame", lambda **_: (b"", metadata))
    monkeypatch.setattr(frames, "resolve", lambda *_: pytest.fail("legacy file resolution"))
    row = frames.describe("raw", now=1000.0)
    assert row["source"] == "camera_pipeline_ram" and row["provenance"] == "capture"
    assert row["observed_at"] == 999.98 and not row["stale"]
    assert row["file_observed_at"] is None
