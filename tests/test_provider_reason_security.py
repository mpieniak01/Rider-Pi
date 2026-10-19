"""Provider reasons cannot forge logs or mutate configuration when invalid."""

from __future__ import annotations

import io
import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask

from common import provider_state
from services import provider_registry as registry
from services.api_core import http_contract, provider_api


@pytest.fixture
def registry_world(monkeypatch, tmp_path):
    path = tmp_path / "providers.json"
    monkeypatch.setattr(registry, "STATE_FILE", path)
    monkeypatch.setattr(provider_state, "STATE_FILE", path)
    monkeypatch.setattr(registry, "_now", lambda: 1000.0)
    monkeypatch.setattr(
        registry, "_domains", {domain: registry._default_domain_state("fixture") for domain in registry.DOMAINS}
    )
    monkeypatch.setattr(registry, "_pc_health", {"reachable": False, "updated_ts": 0.0})
    monkeypatch.setattr(registry, "_pc_base_url", "https://fixture.invalid:8000")
    monkeypatch.setattr(registry, "_load_error", None)
    events = []
    monkeypatch.setattr(registry, "_publish_provider_state_event", lambda *args: events.append(args))
    registry._save_state()
    save = Mock(wraps=registry._save_state)
    monkeypatch.setattr(registry, "_save_state", save)
    return SimpleNamespace(path=path, events=events, save=save)


@pytest.fixture
def provider_client(registry_world):
    app = Flask(__name__)
    http_contract.install(app, after_request=True)
    app.add_url_rule("/api/providers/<domain>", view_func=provider_api.provider_domain_handler, methods=["PATCH"])
    return app.test_client()


def assert_no_effects(world, before, contents):
    assert registry.get_state_snapshot() == before
    assert (world.path.read_bytes() if world.path.exists() else None) == contents
    world.save.assert_not_called()
    assert world.events == []


@pytest.mark.parametrize(
    "reason",
    [
        pytest.param(None, id="null"),
        pytest.param(False, id="false"),
        pytest.param(0, id="number"),
        pytest.param([], id="list"),
        pytest.param({}, id="object"),
        pytest.param("", id="empty"),
        pytest.param("   ", id="whitespace"),
        pytest.param("x" * 257, id="too-long"),
        pytest.param("operator\rFORGED", id="cr"),
        pytest.param("operator\nFORGED", id="lf"),
        pytest.param("operator\r\nFORGED", id="crlf"),
        pytest.param("operator\tFORGED", id="tab"),
        pytest.param("operator\x00FORGED", id="nul"),
        pytest.param("operator\x1b[31mFORGED", id="ansi"),
        pytest.param("operator\x7fFORGED", id="delete"),
        pytest.param("operator\x85FORGED", id="next-line"),
        pytest.param("operator\u2028FORGED", id="line-separator"),
        pytest.param("operator\u2029FORGED", id="paragraph-separator"),
    ],
)
def test_patch_invalid_reason_is_400_without_registry_file_or_bus_effects(registry_world, provider_client, reason):
    before = registry.get_state_snapshot()
    contents = registry_world.path.read_bytes()

    response = provider_client.patch("/api/providers/voice", json={"target": "pc", "reason": reason})

    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_provider_reason"
    assert_no_effects(registry_world, before, contents)


@pytest.mark.parametrize("persisted", [True, False], ids=["existing-file", "missing-file"])
def test_same_mode_patch_rejects_reason_even_when_no_change_would_be_needed(registry_world, provider_client, persisted):
    if not persisted:
        registry_world.path.unlink()
    before = registry.get_state_snapshot()
    contents = registry_world.path.read_bytes() if persisted else None

    response = provider_client.patch(
        "/api/providers/voice",
        json={"target": "local", "reason": "operator\u2028FORGED"},
        headers={"Accept": "application/vnd.rider.api+json;version=1"},
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_provider_reason"
    assert_no_effects(registry_world, before, contents)


@pytest.mark.parametrize("reason", [None, "operator\nFORGED"], ids=["null", "newline"])
@pytest.mark.parametrize(
    "setter,target",
    [
        pytest.param("domain", "pc", id="domain-change"),
        pytest.param("domain", "local", id="domain-no-op"),
        pytest.param("base-url", "https://changed.invalid:8000", id="base-url-change"),
        pytest.param("base-url", "https://fixture.invalid:8000", id="base-url-no-op"),
    ],
)
def test_direct_setters_reject_reason_before_persistence_or_memory_effects(registry_world, reason, setter, target):
    before = registry.get_state_snapshot()
    contents = registry_world.path.read_bytes()

    if setter == "domain":
        set_provider = registry.set_domain_mode
        arguments = ("voice", target)
    else:
        set_provider = registry.set_pc_base_url
        arguments = (target,)
    with pytest.raises(ValueError, match="^invalid_provider_reason$"):
        set_provider(*arguments, reason=reason)

    assert_no_effects(registry_world, before, contents)


def test_patch_omitted_reason_keeps_manual_default(registry_world, provider_client):
    response = provider_client.patch("/api/providers/voice", json={"target": "pc"})

    assert response.status_code == 200
    assert response.get_json()["state"]["reason"] == "manual"
    assert registry.get_domain_state("voice")["reason"] == "manual"
    assert json.loads(registry_world.path.read_text())["domains"]["voice"]["reason"] == "manual"
    assert registry_world.events[0][1]["reason"] == "manual"
    registry_world.save.assert_called_once_with()


@pytest.mark.parametrize(
    "reason",
    [
        pytest.param("x", id="minimum-length"),
        pytest.param("x" * 256, id="maximum-length"),
        pytest.param("Ręczne przełączenie — żółw łączy się z węzłem", id="polish-unicode"),
    ],
)
def test_printable_reason_is_preserved_in_response_memory_file_bus_and_log(
    registry_world, provider_client, caplog, reason
):
    with caplog.at_level(logging.INFO, logger=registry.LOGGER.name):
        response = provider_client.patch("/api/providers/voice", json={"target": "pc", "reason": reason})

    assert response.status_code == 200
    assert response.get_json()["state"]["reason"] == reason
    assert registry.get_domain_state("voice")["reason"] == reason
    assert json.loads(registry_world.path.read_text())["domains"]["voice"]["reason"] == reason
    assert registry_world.events[0][1]["reason"] == reason
    assert caplog.messages == [f"Provider domain voice changed to pc (reason={reason!r})"]
    registry_world.save.assert_called_once_with()


@pytest.mark.parametrize("sink", ["stream", "file"])
def test_both_update_logs_escape_literal_backslashes_and_url_line_breaks(registry_world, monkeypatch, tmp_path, sink):
    stream = io.StringIO()
    log_path = tmp_path / "provider.log"
    handler = logging.StreamHandler(stream) if sink == "stream" else logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    monkeypatch.setattr(registry.LOGGER, "handlers", [handler])
    monkeypatch.setattr(registry.LOGGER, "level", logging.INFO)
    monkeypatch.setattr(registry.LOGGER, "propagate", False)
    reason = "Ręczne przełączenie: " + r"operator\nFORGED\r\x1b[31m"
    base_url = "https://peer.invalid:8100"

    try:
        registry.set_domain_mode("voice", "pc", reason=reason)
        registry.set_pc_base_url(base_url, reason=reason)
        handler.flush()
        output = stream.getvalue() if sink == "stream" else log_path.read_text(encoding="utf-8")
    finally:
        handler.close()

    assert output.splitlines() == [
        f"INFO Provider domain voice changed to pc (reason={reason!r})",
        f"INFO PC base URL updated to {base_url!r} (reason={reason!r})",
    ]
    assert "\r" not in output
    assert registry_world.save.call_count == 2
