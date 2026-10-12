"""The public HTTP transport rejects malformed/oversized envelopes."""

import json
from io import BytesIO
from types import SimpleNamespace

import pytest

from common.api_client import APIClient, APIError


class Response(BytesIO):
    status = 200

    def __init__(self, payload, mime="application/vnd.rider.api+json;version=1"):
        super().__init__(json.dumps(payload).encode())
        self.headers = {"Content-Type": mime}


def test_client_uses_canonical_media_and_preserves_body():
    calls = []

    def open(request, timeout):
        calls.append((request, timeout))
        return Response({"meta": {"envelope_version": 1}, "ok": True, "data": {}})

    body = {"generation": "original", "ts": 100, "ttl_ms": 500}
    assert APIClient(opener=open).request("/api/control", "POST", body)["ok"]
    request, timeout = calls[0]
    assert json.loads(request.data) == body
    assert request.headers["Accept"] == "application/vnd.rider.api+json;version=1"


@pytest.mark.parametrize("mime", ["application/json", "application/vnd.rider.api+json;version=2"])
def test_client_rejects_different_contract(mime):
    with pytest.raises(APIError, match="unsupported_rider_api_contract"):
        APIClient(opener=lambda *args, **kw: Response({"meta": {"envelope_version": 1}}, mime)).request("/state")


@pytest.mark.parametrize("url", ["file:///tmp/api", "http://user:password@localhost", "http://localhost?token=1"])
def test_bad_url_never_opens_network(url):
    with pytest.raises(ValueError):
        APIClient(url, opener=lambda *a, **k: pytest.fail("network opened"))


def test_response_size_is_bounded():
    value = Response({})
    value.read = lambda length: b" " * length
    with pytest.raises(APIError, match="rider_api_response_oversized"):
        APIClient(opener=lambda *a, **kw: value).request("/state")
