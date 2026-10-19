"""Browser HTTP boundaries run with Flask clients and fake effects only."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from flask import Flask, Response, jsonify, request
from werkzeug.test import EnvironBuilder

from services.api_core import http_security


@pytest.fixture
def world(monkeypatch):
    monkeypatch.delenv("RIDER_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("RIDER_TRUSTED_HOSTS", raising=False)
    app = Flask(__name__)
    http_security.install(app)
    effects = []

    @app.after_request
    def legacy_cors(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers.add("Access-Control-Allow-Origin", "https://stale.example")
        response.headers["Access-Control-Allow-Private-Network"] = "true"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    def observe(**values):
        effects.append((request.method, request.path, request.get_data(), values))
        return jsonify({"ok": True})

    app.add_url_rule("/mutate", view_func=observe, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    for index, path in enumerate(["/api/asr", "/api/voice/asr", "/api/voice/playback", "/api/compute/tasks/<task>"]):
        app.add_url_rule(path, "upload_" + str(index), observe, methods=["POST"])
    app.add_url_rule("/api/voice/playback/cancel", "cancel", observe, methods=["POST"])
    return app.test_client(), effects


def assert_no_cors_grant(response):
    assert not any(key.lower().startswith("access-control-") for key in response.headers.keys())


@pytest.mark.parametrize("method", ["GET", "POST", "OPTIONS"])
def test_untrusted_origin_is_denied_before_any_effect_and_legacy_grant_removed(world, method):
    client, effects = world
    response = client.open(
        "/mutate", method=method, json={"action": "arm"}, headers={"Origin": "https://untrusted.example"}
    )
    assert response.status_code == 403
    assert effects == []
    assert_no_cors_grant(response)
    assert "Origin" in response.vary


@pytest.mark.parametrize(
    "origin",
    [
        "null",
        "*",
        "http://localhost.evil",
        "http://localhost/path",
        "http://localhost?",
        "http://localhost#",
        "http://localhost:80?",
        "http://user@localhost",
        "http://localhost, https://other.example",
    ],
)
def test_origin_must_be_a_single_valid_exact_origin(world, origin):
    client, effects = world
    response = client.post("/mutate", json={}, headers={"Origin": origin})
    assert response.status_code == 403
    assert effects == []
    assert_no_cors_grant(response)


@pytest.mark.parametrize("origin", ["http://localhost", "http://localhost:80"])
def test_same_origin_json_is_accepted_and_cors_is_specific(world, origin):
    client, effects = world
    response = client.post("/mutate", json={"value": 1}, headers={"Origin": origin})
    assert response.status_code == 200
    assert len(effects) == 1
    assert response.headers["Access-Control-Allow-Origin"] == origin
    assert "Access-Control-Allow-Credentials" not in response.headers
    assert "Origin" in response.vary


def test_explicit_venom_origin_supports_json_and_preflight(world, monkeypatch):
    client, effects = world
    monkeypatch.setenv("RIDER_ALLOWED_ORIGINS", "http://localhost:3300, https://venom.example:8443")
    origin = "http://localhost:3300"
    response = client.options(
        "/api/voice/playback",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,x-rider-playback-id,x-rider-playback-ttl-ms",
        },
    )
    assert response.status_code in {200, 204}
    assert effects == []
    assert response.headers["Access-Control-Allow-Origin"] == origin
    allowed = {value.strip().lower() for value in response.headers["Access-Control-Allow-Headers"].split(",")}
    assert {
        "content-type",
        "accept",
        "authorization",
        "x-rider-playback-id",
        "x-rider-playback-ttl-ms",
        "x-rider-params",
    } <= allowed
    response = client.post("/mutate", json={}, headers={"Origin": "https://venom.example:8443"})
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "https://venom.example:8443"


@pytest.mark.parametrize("configured", ["*", "https://*.example", "null", "https://untrusted.example/path"])
def test_invalid_allowlist_entries_never_grant_an_untrusted_origin(world, monkeypatch, configured):
    client, effects = world
    monkeypatch.setenv("RIDER_ALLOWED_ORIGINS", configured)
    response = client.post("/mutate", json={}, headers={"Origin": "https://untrusted.example"})
    assert response.status_code == 403
    assert effects == []
    assert_no_cors_grant(response)


@pytest.mark.parametrize("fetch_site", ["cross-site", "same-site"])
def test_browser_mutation_without_origin_is_denied_by_fetch_metadata(world, fetch_site):
    client, effects = world
    response = client.post("/mutate", json={}, headers={"Sec-Fetch-Site": fetch_site})
    assert response.status_code == 403
    assert effects == []
    assert_no_cors_grant(response)
    assert client.get("/mutate", headers={"Sec-Fetch-Site": fetch_site}).status_code == 200


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH"])
@pytest.mark.parametrize(
    "content_type", [None, "text/plain", "application/x-www-form-urlencoded", "multipart/form-data"]
)
def test_nonempty_json_mutations_reject_simple_content_types(world, method, content_type):
    client, effects = world
    response = client.open("/mutate", method=method, data=json.dumps({"value": 1}), content_type=content_type)
    assert response.status_code == 415
    assert response.get_json()["error"] == "unsupported_content_type"
    assert effects == []


@pytest.mark.parametrize("content_type", ["application/json; charset=utf-8", "application/vnd.rider.api+json"])
def test_json_media_types_keep_cli_clients_working(world, content_type):
    client, effects = world
    response = client.post("/mutate", data="{}", content_type=content_type)
    assert response.status_code == 200
    assert len(effects) == 1
    assert "Access-Control-Allow-Origin" not in response.headers


def test_bodyless_mutations_and_delete_remain_available(world):
    client, effects = world
    assert client.post("/mutate").status_code == 200
    assert client.delete("/mutate").status_code == 200
    assert len(effects) == 2


@pytest.mark.parametrize(
    "path,content_type",
    [
        ("/api/asr", "multipart/form-data; boundary=fixture"),
        ("/api/asr", "application/octet-stream"),
        ("/api/voice/asr", "audio/wav"),
        ("/api/voice/playback", "audio/wav"),
        ("/api/compute/tasks/text.respond", "text/plain; charset=utf-8"),
        ("/api/compute/tasks/vision.depth", "image/jpeg"),
    ],
)
def test_raw_upload_contracts_are_preserved_but_origin_guard_still_applies(world, path, content_type):
    client, effects = world
    response = client.post(path, data=b"fixture bytes", content_type=content_type)
    assert response.status_code == 200
    assert effects[0][2] == b"fixture bytes"
    response = client.post(
        path, data=b"fixture bytes", content_type=content_type, headers={"Origin": "https://untrusted.example"}
    )
    assert response.status_code == 403
    assert len(effects) == 1
    assert_no_cors_grant(response)


def test_playback_cancel_is_json_not_raw_upload(world):
    client, effects = world
    response = client.post("/api/voice/playback/cancel", data="{}", content_type="text/plain")
    assert response.status_code == 415
    assert effects == []


def test_real_api_guard_covers_legacy_force_json_and_binary_output(monkeypatch, tmp_path):
    from services import api_server
    from services.api_core import face_api

    monkeypatch.delenv("RIDER_ALLOWED_ORIGINS", raising=False)
    output = tmp_path / "preview.png"

    def png(payload):
        output.write_bytes(b"PNG fixture")
        return Response(output.read_bytes(), mimetype="image/png")

    monkeypatch.setattr(face_api, "png_response", png)
    client = api_server.app.test_client()
    assert client.get("/healthz", headers={"Origin": "https://untrusted.example"}).status_code == 403
    assert client.post("/face/render", data="{}", content_type="text/plain").status_code == 415
    assert client.post("/face/render", json={}, headers={"Origin": "https://untrusted.example"}).status_code == 403
    assert not output.exists()
    response = client.post("/face/render", json={}, headers={"Origin": "http://localhost"})
    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.data == b"PNG fixture"
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost"


def test_bridge_stop_remains_reachable_from_cli_but_foreign_page_is_blocked(monkeypatch):
    from services import web_motion_bridge

    monkeypatch.delenv("RIDER_ALLOWED_ORIGINS", raising=False)
    sent = []
    monkeypatch.setattr(web_motion_bridge, "submit_control", lambda body: (sent.append(body) or {"ok": True}, 202))
    client = web_motion_bridge.app.test_client()
    response = client.post("/api/stop", json={}, headers={"Origin": "https://untrusted.example"})
    assert response.status_code == 403
    assert sent == []
    response = client.post("/api/stop", json={"request_id": "cli-stop"})
    assert response.status_code == 202
    assert sent == [{"request_id": "cli-stop", "action": "stop"}]
    assert client.get("/api/stop").status_code == 405


def test_domain_worker_rejects_origin_before_profile_or_backend_loading(monkeypatch):
    from apps.voice import domain_worker

    legacy = SimpleNamespace(
        _load_config=lambda: pytest.fail("security rejection must not load voice config"),
        api_asr=lambda: pytest.fail("security rejection must not invoke ASR"),
        api_tts=lambda: pytest.fail("security rejection must not invoke TTS"),
        api_tts_test=lambda: pytest.fail("security rejection must not synthesize audio"),
        api_chat_local=lambda: pytest.fail("security rejection must not invoke chat"),
    )
    monkeypatch.delenv("RIDER_ALLOWED_ORIGINS", raising=False)
    monkeypatch.setattr(
        domain_worker, "requested_domains", lambda: pytest.fail("security must precede domain admission")
    )
    client = domain_worker.create_app(legacy).test_client()
    response = client.post("/api/tts", json={"text": "fixture"}, headers={"Origin": "https://untrusted.example"})
    assert response.status_code == 403
    assert_no_cors_grant(response)


def test_legacy_voice_listener_rejects_origin_before_config_loading(monkeypatch):
    monkeypatch.setenv("VOICE_WEB_LOAD_PROFILE", "0")
    from apps.voice import config, web

    monkeypatch.delenv("RIDER_ALLOWED_ORIGINS", raising=False)
    monkeypatch.setattr(config, "load", lambda *args, **kwargs: pytest.fail("rejected voice request loaded config"))
    response = web.app.test_client().post(
        "/api/chat", json={"messages": []}, headers={"Origin": "https://untrusted.example"}
    )
    assert response.status_code == 403
    assert_no_cors_grant(response)


@pytest.mark.parametrize("body,expected", [(b'{"value":1}', 415), (b"", 200)])
def test_terminated_wsgi_input_cannot_hide_non_json_body(world, body, expected):
    client, effects = world
    response = client.post(
        "/mutate", data=body, environ_overrides={"CONTENT_LENGTH": "", "wsgi.input_terminated": True}
    )
    assert response.status_code == expected
    assert len(effects) == (1 if expected == 200 else 0)


@pytest.mark.parametrize("host", ["attacker.example", "localhost.attacker.example", "192.168.1.14.attacker.example"])
def test_matching_origin_and_untrusted_host_cannot_rebind_browser_authority(world, host):
    client, effects = world
    response = client.post("/mutate", json={"action": "fixture"}, headers={"Host": host, "Origin": "http://" + host})
    assert response.status_code == 400
    assert response.get_json()["error"] == "host_not_allowed"
    assert effects == []
    assert_no_cors_grant(response)


@pytest.mark.parametrize("host", ["192.168.1.14:8080", "127.0.0.1:8080", "[::1]:8080"])
def test_numeric_lan_and_loopback_hosts_keep_same_origin_access(world, host):
    client, effects = world
    response = client.post("/mutate", json={}, headers={"Host": host, "Origin": "http://" + host})
    assert response.status_code == 200
    assert len(effects) == 1


def test_operator_can_explicitly_trust_a_reverse_proxy_hostname(world, monkeypatch):
    client, effects = world
    monkeypatch.setenv("RIDER_TRUSTED_HOSTS", "rider.example")
    response = client.post("/mutate", json={}, headers={"Host": "rider.example", "Origin": "http://rider.example"})
    assert response.status_code == 200
    assert len(effects) == 1


@pytest.mark.parametrize("host", ["[::1", "localhost:bad", "user@localhost", "localhost/path"])
def test_malformed_host_is_rejected_without_handler_effect(world, host):
    client, effects = world
    environ = EnvironBuilder(
        path="/mutate", method="POST", json={}, headers={"Origin": "http://localhost"}
    ).get_environ()
    environ["HTTP_HOST"] = host
    response = Response.from_app(client.application, environ)
    assert response.status_code == 400
    assert effects == []
