"""Decode/cache metadata tests with fake ZMQ and fake image decoder only."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from common import frame_stream
from common.data_quality import sample_status


@pytest.fixture
def client(monkeypatch):
    frame = np.zeros((2, 2, 3), dtype=np.uint8)
    metadata = {"mtime": 1000, "ts": 1000.1}
    sock = SimpleNamespace(recv_multipart=lambda *a: [b"camera.frame.raw", json.dumps(metadata).encode(), b"fakejpeg"])

    # SimpleNamespace is not hashable; only the actual dictionary key is needed.
    class Socket:
        def recv_multipart(self, *a):
            return sock.recv_multipart(*a)

    socket = Socket()
    poller = SimpleNamespace(poll=lambda timeout: [(socket, 1)])
    monkeypatch.setattr(frame_stream, "cv2", SimpleNamespace(imdecode=lambda *a: frame, IMREAD_COLOR=1))
    monkeypatch.setattr(frame_stream, "np", np)
    monkeypatch.setattr(frame_stream, "zmq", SimpleNamespace(NOBLOCK=0, Again=RuntimeError))
    instance = object.__new__(frame_stream.FrameStreamClient)
    instance._return_last, instance._copy_frame = True, True
    instance._last_frame = None
    instance._last_metadata = {}
    instance._sock, instance._poller = socket, poller
    return instance, metadata, poller


def test_cached_frame_keeps_capture_time_and_becomes_stale(client):
    instance, _, poller = client
    assert instance.recv(0) is not None
    assert instance.metadata["observed_at"] == 1000
    assert sample_status(instance.metadata, max_age_s=0.5, now=1000.2)["ready"]
    poller.poll = lambda timeout: []
    assert instance.recv(0) is not None
    assert instance.metadata["observed_at"] == 1000
    assert not sample_status(instance.metadata, max_age_s=0.5, now=1001)["ready"]


@pytest.mark.parametrize(
    "fields",
    [
        {"mtime": None},
        {"mtime": True},
        {"mtime": float("nan")},
        {"observed_at": None},
        {"observed_at": 1001},
        {"error": "camera_failed"},
    ],
)
def test_unknown_source_time_does_not_become_publication_time(client, fields):
    instance, metadata, _ = client
    metadata.update(fields)
    assert instance.recv(0) is not None  # Pixels can remain inspectable by the operator.
    assert not sample_status(instance.metadata, max_age_s=0.5, now=1000.2)["ready"]


def test_metadata_returns_copy(client):
    instance, _, _ = client
    instance.recv(0)
    value = instance.metadata
    value["observed_at"] = 2000
    assert instance.metadata["observed_at"] == 1000
