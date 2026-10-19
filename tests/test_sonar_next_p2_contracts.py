"""P2 boundary contracts use inert objects, AST-loaded parser and fake transports."""

from __future__ import annotations

import ast
import io
import json
import logging
import re
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from apps.choreographer import main as choreographer
from apps.compute.client import ComputeClient, ComputeError, PendingJob
from apps.compute.decision_lease import DecisionLease
from apps.compute.navigation import NavigationRunner
from apps.motion.main import _SimAdapter
from apps.navigator.quality import NavigationQuality
from apps.odometry.main import OdometryEstimator
from common.api_client import APIClient, APIError
from common.frame_stream import FrameStreamClient


@pytest.fixture
def speed_parser():
    # Avoid the service module's stdout reconfiguration and process path setup.
    path = Path(__file__).parents[1] / "apps/nlu/main.py"
    tree = ast.parse(path.read_text())
    names = {"_re_pct", "_re_spd"}
    nodes = [
        node
        for node in tree.body
        if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in node.targets))
        or (isinstance(node, ast.FunctionDef) and node.name == "extract_speed")
    ]
    namespace = {"re": re}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


@pytest.mark.parametrize(
    "text,capture,expected",
    [
        ("na 0,6", "0,6", 0.6),
        ("do1.00", "1.00", 1.0),
        ("0.5x", "0", 0.0),
        ("0.5é", "0", 0.0),
        ("10", "0", 0.0),
        ("20.6", "0.6", 0.6),
        ("x0.5", "0.5", 0.5),
        ("0_", None, None),
        ("1.1", "1", 1.0),
        ("1.01", "1", 1.0),
        ("0.٥", "0.٥", 0.5),
        ("1.٠", "1", 1.0),
        ("0x", None, None),
        ("1x", None, None),
        ("0.000end", "0", 0.0),
        ("1000", "0", 0.0),
        ("na    ", None, None),
        ("\u00a00.6", "0.6", 0.6),
        ("0\u0301", "0", 0.0),
        ("0\u200d", "0", 0.0),
        ("na 0.6 i 90%", "0.6", 0.9),
        ("999% na 0.6", "0.6", 1.0),
    ],
)
def test_speed_capture_word_boundaries_and_percentage_priority(speed_parser, text, capture, expected):
    match = speed_parser["_re_spd"].search(text)
    actual_capture = match.group(1) if match else None
    assert actual_capture == capture
    actual_speed = speed_parser["extract_speed"](text)
    assert actual_speed == expected


def test_speed_rejects_long_whitespace_suffix_without_repeated_prefix_search(speed_parser):
    text = " " * 100_000 + "not_a_number"
    assert speed_parser["extract_speed"](text) is None
    assert speed_parser["extract_speed"](text + " na 0,6") == 0.6


@pytest.mark.parametrize(
    "feedback,deadline,wait,expected_calls,active",
    [
        (1.0, 1.0, True, ["stop"], False),
        (2.0, 1.0, True, ["wait"], True),
        (None, 1.0, False, ["wait", "stop"], False),
        (2.0, 2.0, False, [], True),
        (None, None, False, [], True),
    ],
)
def test_lease_expiry_preserves_short_circuit_and_exact_boundary(feedback, deadline, wait, expected_calls, active):
    calls = []
    lease = DecisionLease({}, "fixture", None, lambda: calls.append("stop"), clock=lambda: 1.0)
    lease.feedback_deadline = feedback
    lease.deadline = deadline
    lease._wait_for_feedback = lambda now: calls.append("wait") or wait
    assert lease.tick() is active
    assert calls == expected_calls
    if not active:
        assert lease.reason == "decision_timeout"
        assert lease.feedback_deadline is None
        assert lease.deadline is None


def test_pending_ack_snapshot_can_remove_multiple_executed_rows():
    runner = SimpleNamespace(
        pending_motion_acks={"a": 1.0, "b": 1.0, "waiting": 2.0},
        clock=lambda: 1.0,
    )
    safety = {"recent_acks": [{"request_id": key, "status": "executed", "accepted": True} for key in ("a", "b")]}
    NavigationRunner._check_pending_acks(runner, safety)
    assert runner.pending_motion_acks == {"waiting": 2.0}


def test_capacity_eviction_removes_only_first_terminal_job_before_iterator_resumes():
    client = ComputeClient.__new__(ComputeClient)
    client._jobs = {
        str(index): PendingJob({}, 1.0, observation={"state": "succeeded" if index in {1, 2} else "running"})
        for index in range(32)
    }
    client._admit_job_capacity()
    assert len(client._jobs) == 31
    assert "1" not in client._jobs
    assert "2" in client._jobs
    assert "0" in client._jobs


@pytest.mark.parametrize(
    "code,expected",
    [
        ("valid_123", "valid_123"),
        ("échec", "compute_http_error"),
        ("Ａ", "compute_http_error"),
        ("x" * 101, "compute_http_error"),
    ],
)
def test_compute_error_codes_remain_bounded_ascii(code, expected):
    response = json.dumps({"detail": {"code": code}}).encode()
    client = ComputeClient(
        "http://fixture.invalid",
        "fixture",
        "test-token",
        "boot1",
        transport=SimpleNamespace(request=lambda *args: (400, {}, response)),
    )
    with pytest.raises(ComputeError) as caught:
        client._request("GET", "/fixture")
    assert caught.value.code == expected
    assert caught.value.status == 400


@pytest.mark.parametrize("error", [URLError("fixture"), OSError("fixture")])
def test_api_transport_still_catches_oserror_subclasses(error):
    def unavailable(*args, **kwargs):
        raise error

    client = APIClient("http://fixture.invalid", opener=unavailable)
    with pytest.raises(APIError, match="rider_api_unavailable") as caught:
        client.request("/fixture")
    assert caught.value.__cause__ is error


@pytest.mark.parametrize("data", [b"\xff", b"not json"])
def test_api_invalid_encoding_and_json_close_response(data):
    response = io.BytesIO(data)
    client = APIClient("http://fixture.invalid", opener=lambda *args, **kwargs: response)
    with pytest.raises(APIError, match="invalid_rider_api_response"):
        client.request("/fixture")
    assert response.closed


def test_http_error_retains_api_envelope_instead_of_becoming_transport_failure():
    payload = {"meta": {"envelope_version": 1}, "error": {"code": "fixture_rejected"}}
    error = HTTPError(
        "http://fixture.invalid/fixture",
        409,
        "fixture",
        {"Content-Type": "application/vnd.rider.api+json;version=1"},
        io.BytesIO(json.dumps(payload).encode()),
    )

    def rejected(*args, **kwargs):
        raise error

    client = APIClient("http://fixture.invalid", opener=rejected)
    with pytest.raises(APIError, match="fixture_rejected") as caught:
        client.request("/fixture")
    assert caught.value.response == payload
    assert error.closed


@pytest.mark.parametrize("metadata", [b"\xff", b"not json", None])
def test_frame_invalid_encoding_json_and_type_remain_rejected(metadata):
    client = FrameStreamClient.__new__(FrameStreamClient)
    # A type error must come from json.loads, beyond the length guard.
    value = [1] if metadata is None else metadata
    assert client._candidate([b"fixture", value, b"\xff\xd8\xffjpeg"]) is None


def test_simulated_noop_adapter_retains_keyword_contracts():
    adapter = _SimAdapter()
    assert adapter.enable_balance(enabled=True) is True
    assert adapter.set_height(height=90) is True
    assert adapter.action(name="wave") is False
    assert adapter._moving is False


def test_rejected_autonomous_motion_retains_requested_keyword_contract():
    calls = []
    quality = SimpleNamespace(
        navigation_quality=lambda: {"data_error": None},
        _quality_failure=lambda reason, **options: calls.append((reason, options)),
    )
    assert NavigationQuality._motion_data_permitted(quality, lx=0.1, az=0.2) is False
    assert calls == [("navigation_traversal_unverified", {"stop": True})]


def test_requested_odometry_values_never_become_executed_motion_evidence():
    estimator = SimpleNamespace(x=5.0, y=6.0)
    assert OdometryEstimator.update_motion_command(estimator, lx=1.0, az=2.0) is False
    assert vars(estimator) == {"x": 5.0, "y": 6.0}


def test_failed_choreography_publish_keeps_traceback_and_does_not_retry(caplog):
    calls = []

    def publish(*args, **kwargs):
        calls.append((args, kwargs))
        raise RuntimeError("fixture publish failure")

    with caplog.at_level(logging.ERROR, logger=choreographer.LOG.name):
        choreographer.execute_action(SimpleNamespace(publish=publish), {"topic": "face.expression", "payload": {}})
    assert calls == [(("face.expression", {}), {"add_ts": True})]
    assert len(caplog.records) == 1
    assert caplog.records[0].exc_info[0] is RuntimeError
    assert "Failed to publish to face.expression" in caplog.records[0].getMessage()
