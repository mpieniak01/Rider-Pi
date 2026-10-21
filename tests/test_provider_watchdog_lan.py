"""Legacy watchdog diagnostics with fake transports; no network or hardware."""

import json
import urllib.error
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.compute import lan_transport
from apps.compute.errors import ComputeError
from services import provider_watchdog as watchdog

URL = "http://transport.fixture:3300"
OPTIONS = {"transport_profile": "trusted_lan", "expected_peer_id": "a" * 32}


@pytest.fixture
def legacy(monkeypatch):
    client = Mock(spec=["request", "close"])
    factory = Mock(return_value=client)
    health, fallback = Mock(), Mock()
    monkeypatch.setattr(lan_transport, "PeerHTTPTransport", factory)
    monkeypatch.setattr(
        watchdog,
        "registry",
        SimpleNamespace(
            DOMAINS=("vision", "voice", "text"),
            get_pc_base_url=lambda: URL,
            get_pc_transport_options=lambda: OPTIONS,
            update_pc_health=health,
        ),
    )
    monkeypatch.setattr(watchdog, "_fallback_to_local", fallback)
    return SimpleNamespace(client=client, factory=factory, health=health, fallback=fallback)


def assert_failure(world, expected_status, expected_reason):
    count, status = watchdog._capability_cycle(watchdog.FAIL_THRESHOLD - 1, "online")
    assert (count, status) == (watchdog.FAIL_THRESHOLD, expected_status)
    fields = world.health.call_args.kwargs
    assert fields["reachable"] is False
    assert fields["status"] == expected_status
    assert fields["refresh"] is False
    assert fields["latency_ms"] is None
    world.fallback.assert_called_once_with(expected_reason)


@pytest.mark.parametrize(
    "code",
    [
        "transport_connect_failed",
        "transport_resolve_failed",
        "transport_timeout",
        "transport_identity_mismatch",
        "transport_reconnect_backoff",
    ],
)
def test_request_transport_failure_marks_peer_offline_and_unreachable(legacy, code):
    legacy.client.request.side_effect = ComputeError(code, 503)
    assert_failure(legacy, "offline", "pc_unreachable")
    assert code in legacy.health.call_args.kwargs["reason"]
    legacy.client.request.assert_called_once()
    legacy.client.close.assert_called_once_with()


def test_fetch_adapts_only_the_transport_diagnostic_code(legacy):
    failure = ComputeError("transport_timeout", 504)
    legacy.client.request.side_effect = failure
    with pytest.raises(urllib.error.URLError) as caught:
        watchdog._fetch_pc_capabilities(URL)
    assert caught.value.reason == failure.code
    legacy.client.close.assert_called_once_with()


def test_constructor_configuration_failure_remains_an_error(legacy):
    legacy.factory.side_effect = ComputeError("invalid_compute_url", 400)
    assert_failure(legacy, "error", "pc_error")
    assert legacy.health.call_args.kwargs["reason"] == "invalid_compute_url"
    legacy.client.request.assert_not_called()
    legacy.client.close.assert_not_called()


@pytest.mark.parametrize("response", [(503, {}, b"{}"), (200, {}, b"invalid JSON")])
def test_invalid_capabilities_remain_an_error_and_close_transport(legacy, response):
    legacy.client.request.return_value = response
    assert_failure(legacy, "error", "pc_error")
    legacy.client.close.assert_called_once_with()


def test_successful_capabilities_still_close_transport(legacy):
    capabilities = {domain: {} for domain in watchdog.registry.DOMAINS}
    legacy.client.request.return_value = (200, {}, json.dumps(capabilities).encode())
    data, latency = watchdog._fetch_pc_capabilities(URL)
    assert data == capabilities
    assert latency >= 0
    legacy.factory.assert_called_once_with(URL, **OPTIONS)
    legacy.client.close.assert_called_once_with()
