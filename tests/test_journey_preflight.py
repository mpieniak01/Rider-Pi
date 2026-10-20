"""Capability checks share the selected transport and never open another camera owner."""

from types import SimpleNamespace

import pytest
from test_camera_pipeline_prepare import Response, environment as environment, publish

from apps.compute import stream_prepare
from apps.compute.client import ComputeError


def test_snapshot_journey_checks_selected_host_without_starting_stream(monkeypatch):
    monkeypatch.setattr(stream_prepare, "native", lambda: False)
    monkeypatch.setattr(stream_prepare, "snapshot", lambda: {"revision": 1})
    requests = []

    def receive(req, timeout):
        requests.append(req)
        assert timeout <= 0.8
        return Response({"navigation_journey_version": 1})

    result = stream_prepare.prepare_stream(
        selection={"url": "http://selected/api/v1/rider/compute", "device_id": "device", "token": "isolated"},
        opener=SimpleNamespace(open=receive),
        journey_version=1,
        timeout_s=0.8,
    )
    assert result is None
    assert [row.full_url for row in requests] == ["http://selected/api/v1/rider/compute/vision/status"]
    assert requests[0].headers["X-rider-device"] == "device"


@pytest.mark.parametrize("capability", [None, False, True, 0, 2, "1"])
def test_snapshot_journey_rejects_host_missing_exact_capability(monkeypatch, capability):
    monkeypatch.setattr(stream_prepare, "native", lambda: False)
    monkeypatch.setattr(stream_prepare, "snapshot", lambda: {"revision": 1})
    with pytest.raises(ComputeError, match="navigation_journey_update_required"):
        stream_prepare.prepare_stream(
            selection={"url": "http://selected", "device_id": "device", "token": "isolated"},
            opener=SimpleNamespace(open=lambda *_args, **_kwargs: Response({"navigation_journey_version": capability})),
            journey_version=1,
        )


def test_native_journey_uses_existing_stream_handshake_for_both_capabilities(environment):
    producer, selection, _ = environment
    source = publish(producer)
    requests = []

    def receive(req, timeout):
        requests.append(req)
        return Response({"navigation_journey_version": 1, "stream": {"ready": True, "latest_source": source}})

    result = stream_prepare.prepare_stream(selection=selection, opener=SimpleNamespace(open=receive), journey_version=1)
    assert result["latest_source"] == source
    assert len(requests) == 1
    assert requests[0].full_url.endswith("/vision/status?stream=true")


def test_native_old_host_rejected_even_when_its_stream_is_ready(environment):
    producer, selection, _ = environment
    source = publish(producer)
    with pytest.raises(ComputeError, match="navigation_journey_update_required"):
        stream_prepare.prepare_stream(
            selection=selection,
            opener=SimpleNamespace(
                open=lambda *_args, **_kwargs: Response({"stream": {"ready": True, "latest_source": source}})
            ),
            journey_version=1,
        )
