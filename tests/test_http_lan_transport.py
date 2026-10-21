"""LAN fixtures bind only loopback; no robot, UART, camera or actuator calls."""

import contextlib
import http.client
import json
import socket
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from apps.compute import lan_transport, stream_prepare
from apps.compute.client import ComputeClient, ComputeError, HTTPTransport
from apps.compute.navigation_transport import PREFIX, NavigationHTTPTransport
from apps.compute.stream_transport import StreamStatusTransport
from common.compute_url import validate_compute_url
from services import compute_config, provider_registry, provider_watchdog
from tests.test_compute_client import Clock, Transport, submit

PEER = "a" * 32
OPTIONS = {"transport_profile": "trusted_lan", "expected_peer_id": PEER}


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    lan_transport._GATES.clear()
    monkeypatch.setenv("RIDER_COMPUTE_CONFIG", str(tmp_path / "compute.json"))
    monkeypatch.setenv("RIDER_COMPUTE_STATUS", str(tmp_path / "status.json"))
    monkeypatch.setenv("FEATURE_STATE_PATH", str(tmp_path / "features.json"))
    monkeypatch.setenv("RIDER_COMPUTE_TOKEN", "fixture-only-token")
    monkeypatch.delenv("PROVIDER_PC_TRANSPORT_PROFILE", raising=False)
    monkeypatch.delenv("PROVIDER_PC_EXPECTED_PEER_ID", raising=False)
    yield
    lan_transport._GATES.clear()


@pytest.fixture
def lan(monkeypatch):
    address, lookups = ["127.0.0.1"], []
    original = socket.getaddrinfo

    def resolve(host, port, *args, **kwargs):
        if host == "transport.fixture":
            lookups.append(address[0])
            if address[0] is None:
                raise socket.gaierror("fixture unavailable")
            # Swap two isolated server endpoints. The sandbox intentionally
            # admits only literal 127.0.0.1, so DNS changes are fixture tuples.
            port = servers[1].server_port if address[0] == "127.0.0.2" else port
            host = "127.0.0.1"
        return original(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    states = []
    servers, workers = [], []
    for _ in range(2):
        state = {"peer_id": PEER, "role": "venom", "version": 1, "mode": "good", "rows": [], "wire": Transport()}
        states.append(state)

        def handler(config):
            class Handler(BaseHTTPRequestHandler):
                protocol_version = "HTTP/1.1"

                def do_GET(self):
                    self.reply()

                def do_POST(self):
                    self.reply()

                def do_DELETE(self):
                    self.reply()

                def reply(self):
                    body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                    config["rows"].append((self.client_address, self.command, self.path, dict(self.headers), body))
                    code, mime = 200, "application/json"
                    if self.path == lan_transport.IDENTITY_PATH:
                        data = json.dumps(
                            {
                                "protocol_version": config["version"],
                                "peer_id": config["peer_id"],
                                "service_role": config["role"],
                            }
                        ).encode()
                        if config["mode"] == "delay":
                            time.sleep(0.08)
                        if config["mode"] == "redirect":
                            code, data = 302, b""
                        elif config["mode"] == "oversize":
                            data = b"x" * 4097
                        elif config["mode"] == "invalid":
                            data = b"invalid"
                        elif config["mode"] == "mime":
                            mime = "text/html"
                    elif self.path.endswith("/vision/status") or self.path.endswith("/vision/status?stream=true"):
                        data = b'{"navigation_journey_version":1,"stream":{}}'
                    elif self.path.endswith("/vision/decision"):
                        data = b'{"action":"stop"}'
                    elif self.path == "/providers/capabilities":
                        data = b'{"vision":{},"voice":{},"text":{}}'
                    elif self.path == "/redirect":
                        code, data = 307, b""
                    elif self.path == "/oversize":
                        data = b"x" * 65
                    elif self.path.startswith('/api/v1/rider/compute/'):
                        headers = dict(self.headers.items())
                        code, response_headers, data = config["wire"].request(
                            self.command, self.path.removeprefix('/api/v1/rider/compute'), headers, body, 2
                        )
                        mime = response_headers.get("Content-Type", "application/json")
                    else:
                        data = b'{}'
                    if config["mode"] == "drop_post" and self.command == "POST" and self.path.endswith("/jobs"):
                        self.close_connection = True
                        self.connection.shutdown(socket.SHUT_RDWR)
                        self.connection.close()
                        return
                    self.send_response(code)
                    self.send_header("Content-Type", mime)
                    self.send_header("Content-Length", str(len(data)))
                    if config["mode"] == "close" and self.path == lan_transport.IDENTITY_PATH:
                        self.send_header("Connection", "close")
                    if 300 <= code < 400:
                        self.send_header("Location", "/never-follow")
                    self.end_headers()
                    with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                        self.wfile.write(data)

                def log_message(self, *_):
                    pass

            return Handler

        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(state))
        server.daemon_threads = True
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        servers.append(server)
        workers.append(worker)
    clock = Clock()
    try:
        yield SimpleNamespace(
            url="http://transport.fixture:" + str(servers[0].server_port),
            states=states,
            address=address,
            lookups=lookups,
            clock=clock,
        )
    finally:
        for server, worker in zip(servers, workers):
            server.shutdown()
            server.server_close()
            worker.join(1)


def peer(fixture, **kwargs):
    return lan_transport.PeerHTTPTransport(fixture.url, clock=fixture.clock, **OPTIONS, **kwargs)


def test_profile_is_explicit_and_old_configuration_keeps_secure_default():
    row = compute_config.configure("https://venom.fixture:8443", "test")
    path = compute_config.config_path()
    data = json.loads(path.read_text())
    data["executors"]["venom"].pop("transport_profile")
    data["executors"]["venom"].pop("expected_peer_id")
    data["selected_executor"] = "venom"
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    selected = compute_config.selected_executor()
    assert selected["transport_profile"] == "secure"
    assert selected["expected_peer_id"] is None
    assert path.read_bytes() == before
    assert compute_config.snapshot()["revision"] == row["revision"]
    with pytest.raises(ValueError, match="compute_configuration_invalid"):
        compute_config.configure("http://venom.fixture:3300", "test")


@pytest.mark.parametrize(
    "profile,expected",
    [
        ("trusted_lan", None),
        ("unknown", PEER),
        ([], PEER),
        ("trusted_lan", []),
        ("trusted_lan", "x" * 32),
        ("trusted_lan", "A" * 32),
    ],
)
def test_invalid_pairing_is_refused_before_persistence(profile, expected):
    with pytest.raises(ValueError, match="compute_configuration_invalid"):
        compute_config.configure(
            "http://venom.fixture:3300", "test", transport_profile=profile, expected_peer_id=expected
        )
    assert not compute_config.config_path().exists()


@pytest.mark.parametrize(
    "url",
    [
        "http://u:p@host",
        "http://host/path",
        "http://host?q=1",
        "http://host#x",
        "http://host:",
        "http://host:99999",
        "http://host\\other",
        "http://host\n",
        "http://host ",
    ],
)
def test_lan_does_not_relax_other_url_boundaries(url):
    with pytest.raises(ValueError):
        validate_compute_url(url, **OPTIONS)


def test_identity_precedes_token_on_the_same_socket(lan):
    transport = HTTPTransport(lan.url, clock=lan.clock, **OPTIONS)
    assert lan.states[0]["rows"] == []
    assert transport.host == "transport.fixture"
    try:
        transport.request(
            "GET", "/capabilities", {"Authorization": "Bearer fixture-token", "X-Rider-Device": "test"}, b"", 1
        )
        rows = lan.states[0]["rows"]
        assert [row[2] for row in rows] == [lan_transport.IDENTITY_PATH, "/api/v1/rider/compute/capabilities"]
        assert rows[0][0] == rows[1][0]
        assert "Authorization" not in rows[0][3]
        assert "X-Rider-Device" not in rows[0][3]
        assert rows[1][3]["Authorization"] == "Bearer fixture-token"
        assert transport.peer.connection.auto_open == 0
    finally:
        transport.close()


@pytest.mark.parametrize(
    "mode,code",
    [
        ("close", "transport_identity_connection_closed"),
        ("redirect", "transport_identity_redirect_denied"),
        ("oversize", "transport_identity_api_invalid"),
        ("invalid", "transport_identity_api_invalid"),
        ("mime", "transport_identity_api_invalid"),
    ],
)
def test_bad_identity_and_connection_close_send_no_credentials(lan, mode, code):
    lan.states[0]["mode"] = mode
    transport = peer(lan)
    try:
        with pytest.raises(ComputeError, match=code):
            transport.request(
                "POST", "/private", {"Authorization": "Bearer should-never-leak"}, b"input", 1, max_bytes=64
            )
        assert len(lan.states[0]["rows"]) == 1
        assert "should-never-leak" not in repr(lan.states[0]["rows"])
        assert transport.connection is None
    finally:
        transport.close()


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("peer_id", "b" * 32, "transport_identity_mismatch"),
        ("role", "rider_pi", "transport_identity_api_invalid"),
        ("version", True, "transport_identity_api_invalid"),
    ],
)
def test_wrong_peer_role_and_protocol_are_fail_closed(lan, field, value, code):
    lan.states[0][field] = value
    transport = peer(lan)
    try:
        with pytest.raises(ComputeError, match=code):
            transport.request("GET", "/private", {"Authorization": "private"}, b"", 1, max_bytes=64)
        assert [row[2] for row in lan.states[0]["rows"]] == [lan_transport.IDENTITY_PATH]
        assert transport.status()["error"] == code
    finally:
        transport.close()


def test_dns_change_reopens_same_canonical_host_then_verifies_again(lan):
    transport = peer(lan)
    try:
        transport.request("GET", "/private", {"Authorization": "fixture"}, b"", 1, max_bytes=64)
        lan.address[0] = "127.0.0.2"
        lan.clock.sleep(2)
        transport.request("GET", "/private", {"Authorization": "fixture"}, b"", 1, max_bytes=64)
        assert lan.lookups == ["127.0.0.1", "127.0.0.2"]
        assert transport.canonical_url == lan.url
        assert transport.generation == 2
        assert [row[2] for row in lan.states[1]["rows"]] == [lan_transport.IDENTITY_PATH, "/private"]
    finally:
        transport.close()


def test_impostor_after_dns_change_gets_no_token_or_old_request(lan):
    transport = peer(lan)
    try:
        transport.request("GET", "/private", {"Authorization": "fixture"}, b"", 1, max_bytes=64)
        lan.address[0] = "127.0.0.2"
        lan.states[1]["peer_id"] = "b" * 32
        lan.clock.sleep(2)
        with pytest.raises(ComputeError, match="transport_identity_mismatch"):
            transport.request("POST", "/private", {"Authorization": "fixture"}, b"old-input", 1, max_bytes=64)
        assert len(lan.states[1]["rows"]) == 1
        assert "Authorization" not in lan.states[1]["rows"][0][3]
        assert transport.status()["state"] == "identity_mismatch"
    finally:
        transport.close()


def test_resolve_failure_backoff_is_shared_bounded_and_demand_only(lan):
    lan.address[0] = None
    one, two = peer(lan), peer(lan)
    try:
        with pytest.raises(ComputeError, match="transport_resolve_failed"):
            one.prepare(1)
        for client in (one, two):
            with pytest.raises(ComputeError, match="transport_reconnect_backoff"):
                client.prepare(1)
        assert lan.lookups == [None]
        for _ in range(8):
            lan.clock.sleep(31)
            with pytest.raises(ComputeError, match="transport_resolve_failed"):
                two.prepare(1)
            assert 0 < two.status()["retry_after_s"] <= 30
        count = len(lan.lookups)
        lan.clock.sleep(1000)
        assert len(lan.lookups) == count  # no background resolver or timer
        lan.address[0] = "127.0.0.1"
        two.prepare(1)
        assert two.status()["state"] == "online"
        two.close()
        with pytest.raises(ComputeError, match="compute_client_closed"):
            two.prepare(1)
        assert len(lan.lookups) == count + 1
    finally:
        one.close()
        two.close()


def test_identity_timeout_consumes_same_request_budget_without_token(lan):
    lan.states[0]["mode"] = "delay"
    transport = lan_transport.PeerHTTPTransport(lan.url, **OPTIONS)
    try:
        with pytest.raises(ComputeError, match="transport_timeout"):
            transport.request("POST", "/private", {"Authorization": "private"}, b"data", 0.02, max_bytes=64)
        assert len(lan.states[0]["rows"]) == 1
        assert "Authorization" not in lan.states[0]["rows"][0][3]
    finally:
        transport.close()


@pytest.mark.parametrize(
    "path,code", [("/redirect", "transport_redirect_denied"), ("/oversize", "transport_response_too_large")]
)
def test_authenticated_response_bounds_and_redirect_do_not_replay(lan, path, code):
    transport = peer(lan)
    try:
        with pytest.raises(ComputeError, match=code):
            transport.request("POST", path, {"Authorization": "fixture"}, b"input", 1, max_bytes=64)
        assert [row[2] for row in lan.states[0]["rows"]] == [lan_transport.IDENTITY_PATH, path]
        assert transport.connection is None
    finally:
        transport.close()


def test_old_job_is_dropped_on_generation_change_and_never_replayed(lan):
    client = ComputeClient(
        lan.url, "test", "fixture", "boot1", clock=lan.clock, wall_clock=lan.clock, sleeper=lan.clock.sleep, **OPTIONS
    )
    try:
        job = submit(client)
        lan.address[0] = "127.0.0.2"
        lan.clock.sleep(2)
        with pytest.raises(ComputeError, match="transport_generation_changed"):
            client.result(job)
        assert not client._jobs
        assert client._lease is None
        assert [row[2] for row in lan.states[1]["rows"]] == [lan_transport.IDENTITY_PATH]
        with pytest.raises(ComputeError, match="stale_compute_sequence"):
            submit(client)
        next_job = submit(client, sequence=2, captured_at=lan.clock())
        assert client.result(next_job)["data"]["text"] == "ok"
        assert (
            len(
                [
                    row
                    for row in lan.states[0]["rows"] + lan.states[1]["rows"]
                    if row[1:3] == ("POST", "/api/v1/rider/compute/jobs")
                ]
            )
            == 2
        )
    finally:
        client.close()


def test_navigation_reconnect_drops_current_frame_and_keeps_no_authority(lan):
    transport = NavigationHTTPTransport(lan.url, clock=lan.clock, **OPTIONS)

    def req():
        return urllib.request.Request(
            lan.url + PREFIX + "decision", data=b"fresh-frame", headers={"Authorization": "fixture"}
        )

    try:
        assert json.load(transport.open(req(), timeout=1))["action"] == "stop"
        lan.address[0] = "127.0.0.2"
        lan.clock.sleep(2)
        request = req()
        with pytest.raises(ComputeError, match="transport_generation_changed"):
            transport.open(request, timeout=1)
        assert len(lan.states[1]["rows"]) == 1
        assert json.load(transport.open(req(), timeout=1))["action"] == "stop"
        assert transport.peer.requests == 2
    finally:
        transport.close()


def test_stream_preflight_uses_verified_passive_get_and_closes_owned_client(lan, monkeypatch):
    monkeypatch.setattr(stream_prepare, "native", lambda: False)
    monkeypatch.setattr(stream_prepare, "snapshot", lambda: {"revision": 1})
    selection = {"url": lan.url, "device_id": "test", "token": "fixture", **OPTIONS}
    assert stream_prepare.prepare_stream(selection=selection, journey_version=1, clock=lan.clock) is None
    rows = lan.states[0]["rows"]
    assert [row[1] for row in rows] == ["GET", "GET"]
    assert [row[2] for row in rows] == [lan_transport.IDENTITY_PATH, "/api/v1/rider/compute/vision/status"]
    assert "Authorization" not in rows[0][3]
    assert rows[0][0] == rows[1][0]


def test_legacy_lan_uses_same_profile_and_heartbeat_cannot_rebind(lan, monkeypatch, tmp_path):
    monkeypatch.setenv("PROVIDER_PC_TRANSPORT_PROFILE", "trusted_lan")
    monkeypatch.setenv("PROVIDER_PC_EXPECTED_PEER_ID", PEER)
    monkeypatch.setattr(provider_registry, "_pc_base_url", lan.url)
    monkeypatch.setattr(provider_registry, "STATE_FILE", tmp_path / "providers.json")
    data, _ = provider_watchdog._fetch_pc_capabilities(lan.url)
    assert set(data) == {"vision", "voice", "text"}
    assert lan.states[0]["rows"][0][2] == lan_transport.IDENTITY_PATH
    with pytest.raises(ValueError, match="legacy_peer_binding_mismatch"):
        provider_registry.record_pc_heartbeat("http://other.fixture:3300", {})
    assert provider_registry.get_pc_base_url() == lan.url


def test_legacy_heartbeat_never_overwrites_selected_compute(lan, monkeypatch, tmp_path):
    row = compute_config.configure(lan.url, "test", **OPTIONS)
    compute_config.select("venom", row["revision"])
    before = compute_config.config_path().read_bytes()
    monkeypatch.setattr(provider_registry, "STATE_FILE", tmp_path / "providers.json")
    monkeypatch.setattr(provider_registry, "_pc_base_url", "https://legacy.fixture")
    provider_registry.record_pc_heartbeat("https://different.fixture", {})
    assert compute_config.config_path().read_bytes() == before
    assert compute_config.selected_executor()["url"] == lan.url
    assert compute_config.selected_executor()["expected_peer_id"] == PEER


def test_lost_post_ack_is_not_replayed_or_resurrected_after_recovery(lan):
    lan.states[0]["mode"] = "drop_post"
    client = ComputeClient(
        lan.url,
        "test",
        "fixture",
        "boot1",
        clock=lan.clock,
        wall_clock=lan.clock,
        sleeper=lan.clock.sleep,
        **OPTIONS,
    )
    try:
        with pytest.raises(ComputeError, match="transport_connect_failed"):
            submit(client)
        assert not client._jobs
        assert client._lease is None
        assert len([row for row in lan.states[0]["rows"] if row[1:3] == ("POST", "/api/v1/rider/compute/jobs")]) == 1
        assert not any(row[1] == "DELETE" for row in lan.states[0]["rows"])
        lan.clock.sleep(31)
        lan.states[0]["mode"] = "good"
        assert client.capabilities()["executor_id"] == "venom"
        with pytest.raises(ComputeError, match="stale_compute_sequence"):
            submit(client)
        assert len([row for row in lan.states[0]["rows"] if row[1:3] == ("POST", "/api/v1/rider/compute/jobs")]) == 1
    finally:
        client.close()


def test_active_connection_resolves_again_at_bounded_age(lan):
    transport = peer(lan)
    try:
        for _ in range(30):
            transport.request("GET", "/private", {}, b"", 1, max_bytes=64)
            lan.clock.sleep(1)
        assert lan.lookups == ["127.0.0.1"]
        lan.address[0] = "127.0.0.2"
        transport.request("GET", "/private", {}, b"", 1, max_bytes=64)
        assert lan.lookups == ["127.0.0.1", "127.0.0.2"]
        assert transport.generation == 2
    finally:
        transport.close()


@pytest.mark.parametrize("kind", ["stream", "navigation"])
def test_lan_adapters_refuse_other_origins_before_identity(lan, kind):
    if kind == "stream":
        transport = StreamStatusTransport({"url": lan.url, **OPTIONS}, clock=lan.clock)
        path = "/api/v1/rider/compute/vision/status"
        request = urllib.request.Request("http://other.fixture" + path, headers={"Authorization": "private"})
    else:
        transport = NavigationHTTPTransport(lan.url, clock=lan.clock, **OPTIONS)
        request = urllib.request.Request(
            "http://other.fixture" + PREFIX + "decision", data=b"fixture", headers={"Authorization": "private"}
        )
    try:
        with pytest.raises(ComputeError, match="navigation_transport_target_invalid"):
            transport.open(request, timeout=1)
        assert not lan.lookups
    finally:
        transport.close()


def test_nested_transport_diagnostics_exclude_credentials_and_addresses():
    row = compute_config.configure("https://venom.fixture", "test")
    compute_config.record_status(
        "cli",
        {
            "transport": {
                "state": "backoff",
                "error": "transport_resolve_failed",
                "generation": 1,
                "retry_after_s": 1,
                "token": "private-token",
                "url": "private-url",
            }
        },
        revision=row["revision"],
    )
    status = compute_config.observed_status()["domains"]["cli"]["transport"]
    assert set(status) == {"state", "error", "generation", "retry_after_s"}
    assert "private-" not in json.dumps(status)
