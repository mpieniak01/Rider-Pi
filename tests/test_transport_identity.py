"""Persistent identity and browser boundary tests have no hardware dependencies."""

import concurrent.futures
import json
import threading

import pytest
from flask import Flask

from services import transport_identity
from services.api_core import http_contract, transport_api


@pytest.fixture
def identity_file(monkeypatch, tmp_path):
    path = tmp_path / "private" / "identity.json"
    monkeypatch.setenv("RIDER_TRANSPORT_IDENTITY_FILE", str(path))
    return path


def app():
    application = Flask(__name__)
    http_contract.install(application, after_request=True)
    transport_api.register(application)
    return application


def test_identity_is_persistent_private_and_distinct_from_boot(identity_file, monkeypatch):
    first = transport_identity.identity()
    monkeypatch.setenv("RIDER_DEVICE_ID", "other-device")
    second = transport_identity.identity()
    assert second == first
    assert len(first["peer_id"]) == 32
    assert int(first["peer_id"], 16) > 0
    assert set(first) == {"peer_id", "protocol_version", "service_role"}
    assert first["protocol_version"] == 1
    assert first["service_role"] == "rider_pi"
    assert identity_file.stat().st_mode & 0o777 == 0o600


def test_concurrent_first_reads_publish_one_complete_identity(identity_file):
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as workers:
        rows = list(workers.map(lambda _: transport_identity.identity(), range(12)))
    assert all(row == rows[0] for row in rows)
    assert json.loads(identity_file.read_text()) == rows[0]


@pytest.mark.parametrize(
    "data",
    [
        b"bad-json",
        b"x" * 1025,
        b'{"protocol_version":true,"service_role":"rider_pi","peer_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}',
        b'{"protocol_version":1,"service_role":"venom","peer_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}',
    ],
)
def test_corrupt_identity_is_not_silently_rotated(identity_file, data):
    identity_file.parent.mkdir()
    identity_file.write_bytes(data)
    with pytest.raises(ValueError, match="transport_identity_invalid"):
        transport_identity.identity()
    assert identity_file.read_bytes() == data
    response = app().test_client().get("/api/v1/transport/identity")
    assert response.status_code == 503
    assert response.json == {"error": "transport_identity_unavailable"}


def test_symlink_identity_is_refused_without_reading_target(identity_file, tmp_path):
    identity_file.parent.mkdir()
    target = tmp_path / "outside.json"
    target.write_text("private-target")
    identity_file.symlink_to(target)
    response = app().test_client().get("/api/v1/transport/identity")
    assert response.status_code == 503
    assert target.read_text() == "private-target"


def test_identity_is_passive_and_same_origin_lan_remains_explicit(identity_file, monkeypatch):
    monkeypatch.setenv("RIDER_TRUSTED_HOSTS", "robot.fixture")
    client = app().test_client()
    response = client.get(
        "/api/v1/transport/identity",
        base_url="http://robot.fixture:8080",
        headers={"Origin": "http://robot.fixture:8080"},
    )
    assert response.status_code == 200
    assert response.json == transport_identity.identity()
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Access-Control-Allow-Origin"] == "http://robot.fixture:8080"
    assert client.post("/api/v1/transport/identity", json={}).status_code == 405
    assert client.get("/api/v1/transport/identity", base_url="http://unconfigured.fixture").status_code == 400
    assert (
        client.get("/api/v1/transport/identity", headers={"Origin": "http://unconfigured.fixture"}).status_code == 403
    )


def test_identity_envelope_has_own_contract_without_secret_fields(identity_file):
    response = (
        app()
        .test_client()
        .get("/api/v1/transport/identity", headers={"Accept": "application/vnd.rider.api+json;version=1"})
    )
    assert response.status_code == 200
    assert response.json["meta"]["contract_id"] == "rider.transport"
    assert response.json["data"] == transport_identity.identity()
    assert "token" not in json.dumps(response.json)


def test_overlapping_publication_holds_readers_until_single_link(identity_file, monkeypatch):
    from common import secure_files

    published, release, contender_opened = threading.Event(), threading.Event(), threading.Event()
    original_link, original_owned = secure_files.os.link, transport_identity.open_owned

    def link_then_pause(*args, **kwargs):
        original_link(*args, **kwargs)
        published.set()
        if not release.wait(3):
            raise TimeoutError("fixture did not release publication")

    def owned(path):
        descriptor = original_owned(path)
        if published.is_set():
            contender_opened.set()
        return descriptor

    monkeypatch.setattr(secure_files.os, "link", link_then_pause)
    monkeypatch.setattr(transport_identity, "open_owned", owned)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as workers:
        try:
            creator = workers.submit(transport_identity.identity)
            assert published.wait(3)
            assert identity_file.stat().st_nlink == 2
            reader = workers.submit(transport_identity.identity)
            assert contender_opened.wait(3)
            # The reader must wait, rather than report corruption during publish.
            with pytest.raises(concurrent.futures.TimeoutError):
                reader.result(timeout=0.05)
            release.set()
            assert creator.result(timeout=3) == reader.result(timeout=3)
            assert identity_file.stat().st_nlink == 1
        finally:
            release.set()


def test_identity_lock_symlink_is_refused_before_identity_creation(identity_file, tmp_path):
    identity_file.parent.mkdir()
    outside = tmp_path / "outside-lock"
    outside.write_text("untouched")
    identity_file.with_name(identity_file.name + ".lock").symlink_to(outside)
    response = app().test_client().get("/api/v1/transport/identity")
    assert response.status_code == 503
    assert not identity_file.exists()
    assert outside.read_text() == "untouched"
