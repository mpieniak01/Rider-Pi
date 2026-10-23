"""Model catalog remains host-owned; all transport calls are inert fakes."""

import copy
import hashlib
import json
from types import SimpleNamespace

import pytest
from flask import Flask

from apps.compute.client import ComputeError
from apps.compute.navigation_cycle import NavigationCycle
from services import perception_local, perception_proxy as proxy
from services.api_core import navigation_api
from tests.test_perception_selection import choice


@pytest.fixture
def transport(monkeypatch):
    selected = {
        "revision": 7,
        "url": "http://127.0.0.1:18815/api/v1/rider/compute",
        "device_id": "fixture",
        "token": "fixture-only",
        "transport_profile": "secure",
    }
    state = SimpleNamespace(
        status=200, headers={"Content-Type": "application/json"}, body=b'{"models":[]}', calls=[], closed=False
    )
    monkeypatch.setattr(proxy.compute_config, "selected_executor", lambda: selected)
    monkeypatch.setattr(proxy.compute_config, "snapshot", lambda: {"revision": selected["revision"]})

    class Transport:
        def __init__(self, *args, **kwargs):
            state.endpoint = args
            state.options = kwargs

        def request(self, *args, **kwargs):
            state.calls.append((args, kwargs))
            return state.status, state.headers, state.body

        def close(self):
            state.closed = True

    state.transport = Transport
    state.selected = selected
    return state


def test_fresh_host_catalog_only_uses_configured_origin_and_never_persists(transport, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = proxy._request("models", transport_factory=transport.transport)
    assert result == {"models": []}
    assert transport.closed
    args, options = transport.calls[0]
    assert args[:2] == ("GET", "/api/v1/rider/compute/vision/models")
    assert args[2]["X-Rider-Device"] == "fixture"
    assert args[2]["Authorization"] == "Bearer fixture-only"
    assert list(tmp_path.iterdir()) == []
    assert options == {"max_bytes": 128 * 1024}


def test_selected_model_goes_to_host_which_resolves_artifact_not_to_arbitrary_url(transport):
    body = {"revision": 3, "model_id": "fast-scnn-floor"}
    proxy._request("model", body, transport_factory=transport.transport)
    args, _ = transport.calls[0]
    assert args[:2] == ("POST", "/api/v1/rider/compute/vision/model")
    assert json.loads(args[3]) == body
    assert args[4] == 10.0


@pytest.mark.parametrize(
    "body",
    [
        {"revision": True, "model_id": "fast-scnn-floor"},
        {"revision": 0, "model_id": "https://elsewhere"},
        {"revision": 0, "model_id": []},
        {"revision": 0, "model_id": "fast-scnn-floor", "url": "http://elsewhere"},
    ],
)
def test_invalid_proxy_choice_never_connects(transport, body):
    with pytest.raises(ValueError):
        proxy.choose(body)
    assert not transport.calls


@pytest.mark.parametrize(
    "status,headers,body,code",
    [
        (503, {}, b'{"detail":"host_busy"}', "host_busy"),
        (400, {}, b'{"error":"private /path secret"}', "navigation_model_host_unavailable"),
        (302, {}, b'', "navigation_model_host_unavailable"),
        (200, {"Content-Type": "text/html"}, b'{}', "host_response_invalid"),
        (200, {"Content-Type": "application/json"}, b'[]', "host_response_invalid"),
        (200, {"Content-Type": "application/json"}, b'bad', "host_response_invalid"),
        (200, {"Content-Type": "application/json"}, b' ' * (128 * 1024 + 1), "host_response_invalid"),
    ],
)
def test_host_failure_never_fakes_availability(transport, status, headers, body, code):
    transport.status, transport.headers, transport.body = status, headers, body
    with pytest.raises(ComputeError, match=code):
        proxy._request("models", transport_factory=transport.transport)
    assert transport.closed


def test_executor_revision_change_invalidates_old_host_response(transport, monkeypatch):
    monkeypatch.setattr(proxy.compute_config, "snapshot", lambda: {"revision": 99})
    with pytest.raises(ComputeError, match="compute_selection_changed"):
        proxy._request("models", transport_factory=transport.transport)
    assert transport.closed


def test_local_catalog_describes_actual_files_and_never_claims_semantic_drive(tmp_path, monkeypatch):
    folder = tmp_path / "ssd"
    folder.mkdir()
    (folder / "MobileNetSSD_deploy.prototxt").write_bytes(b"definition")
    (folder / "MobileNetSSD_deploy.caffemodel").write_bytes(b"weights")
    monkeypatch.setenv("SSD_MODEL_DIR", str(folder))
    monkeypatch.setenv("TFLITE_MODEL", str(tmp_path / "absent.tflite"))
    profile = {"analysis_location": "local", "local_engine": "ssd", "remote_transport": "snapshots"}
    result = perception_local.catalog(
        {
            "profile": profile,
            "revision": 4,
            "active_profile": dict(profile),
            "state": "active",
            "capabilities": {"local_engines": ["canny", "ssd"]},
        }
    )
    rows = {row["id"]: row for row in result["models"]}
    assert rows["local-canny"]["sha256"] == ""
    digest = hashlib.sha256(
        (hashlib.sha256(b"definition").hexdigest() + hashlib.sha256(b"weights").hexdigest()).encode()
    ).hexdigest()
    assert rows["local-ssd"]["sha256"] == digest
    assert rows["local-ssd"]["loaded"]
    assert rows["local-ssd"]["selectable"]
    assert not rows["local-tflite"]["selectable"]
    assert all(row["drive_supported"] is False for row in rows.values())
    assert str(tmp_path) not in json.dumps(result)
    assert result["active_model_id"] == "local-ssd"


def test_local_current_selection_is_distinct_from_loaded_engine_when_off():
    result = perception_local.catalog(
        {
            "profile": {"analysis_location": "venom", "local_engine": "canny"},
            "revision": 4,
            "active_profile": None,
            "state": "stopped",
            "capabilities": {"local_engines": ["canny"]},
        }
    )
    assert result["selected_model_id"] == "local-canny"
    assert result["active_model_id"] is None
    assert result["provider"] == "venom"


def test_observation_reply_requires_selected_model_and_frame_identity():
    runner = NavigationCycle()
    runner.policy = {"perception": {key: value for key, value in choice().items() if key != "revision"}}
    meta = {"protocol_version": 1, "run_id": "r", "frame_id": "f", "sequence": 1, "config_revision": 5}
    valid = {**meta, "model_id": choice()["model_id"], "artifact_sha256": "a" * 64}
    runner._check_model_reply(valid, meta)
    for patch in (
        {"model_id": "fast-scnn-floor"},
        {"artifact_sha256": "b" * 64},
        {"config_revision": 4},
        {"frame_id": "old"},
    ):
        with pytest.raises(ComputeError, match="model_identity_mismatch"):
            runner._check_model_reply(dict(valid, **patch), meta)


def test_api_maps_selection_busy_and_unavailable_without_private_error(monkeypatch):
    app = Flask(__name__)
    for error, status in [(BlockingIOError("private"), 409), (ValueError("navigation_goal_state_unavailable"), 503)]:

        def fail(error=error):
            raise error

        with app.test_request_context():
            response, code = navigation_api._model_response(fail)
            assert code == status
            assert "private" not in response.get_data(as_text=True)


@pytest.mark.parametrize(
    "envelope",
    [
        {"detail": {"code": "navigation_model_requires_idle_disarmed", "details": {"private": "/server/path"}}},
        {"error": {"code": "navigation_model_requires_idle_disarmed", "details": "fixture-private-context"}},
    ],
)
def test_host_structured_error_preserves_only_safe_code(transport, envelope):
    transport.status = 409
    transport.body = json.dumps(envelope).encode()
    with pytest.raises(ComputeError) as failure:
        proxy._request("model", {"revision": 3, "model_id": "fast-scnn-floor"}, transport_factory=transport.transport)
    assert failure.value.code == "navigation_model_requires_idle_disarmed"
    assert failure.value.status == 409
    assert "private" not in str(failure.value)
    assert "/server/path" not in str(failure.value)
    assert transport.closed


@pytest.mark.parametrize("code", ["private /path", {"not": "a code"}, "", "x" * 129])
def test_structured_error_never_exports_unsafe_code_or_details(transport, code):
    transport.status = 503
    transport.body = json.dumps({"detail": {"code": code, "details": "fixture-private-context"}}).encode()
    with pytest.raises(ComputeError) as failure:
        proxy._request("models", transport_factory=transport.transport)
    assert failure.value.code == "navigation_model_host_unavailable"
    assert "fixture-private-context" not in str(failure.value)
    assert transport.closed
