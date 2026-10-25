"""Optional camera diagnostics cannot change a navigation persistence outcome."""

import json

import pytest
from flask import Flask

from services import camera_pipeline_store, navigation_config
from services.api_core.navigation_api import config_handler


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("failure", [OSError("unreadable"), ValueError("invalid"), KeyError("profile")])
def test_camera_failure_degrades_catalog_without_claiming_navigation_save_failed(
    tmp_path, monkeypatch, method, failure
):
    target = tmp_path / "navigation.json"
    monkeypatch.setenv("RIDER_NAVIGATION_CONFIG", str(target))
    monkeypatch.setattr(navigation_config, "_require_idle_goals", lambda: None)
    monkeypatch.setattr(navigation_config, "_require_navigation_goals_stopped", lambda: None)

    def camera_failure():
        raise failure

    monkeypatch.setattr(camera_pipeline_store, "snapshot", camera_failure)
    body = {"revision": 0, "values": {"speed": 0.12}}
    with Flask(__name__).test_request_context(method=method, json=body if method == "POST" else None):
        response, status = config_handler()
    assert status == 200
    payload = response.get_json()
    config = payload["config"] if method == "POST" else payload
    assert config["behavior_catalog"]["execution_eligible"] is False
    assert config["behavior_catalog"]["reason"] == "camera_pipeline_config_unavailable"
    assert config["model_tuning_supported"] is True
    assert config["motion_limits"] == {"version": 1, "max_motion_ms": 250}
    assert config["perception_tuning"]["version"] == 1
    if method == "POST":
        assert payload['ok'] is True
        assert payload['persisted'] is True
        persisted = json.loads(target.read_text())
        assert persisted["revision"] == config["revision"] == 1
        assert persisted["speed"] == config["speed"] == 0.12
        assert navigation_config.snapshot() == persisted
    else:
        assert config["revision"] == 0
        assert not target.exists()


@pytest.mark.parametrize(
    "provider,eligible,reason",
    [
        ("venom", True, ""),
        ("local", False, "navigation_profile_local_executor"),
    ],
)
def test_valid_camera_provider_retains_execution_eligibility(monkeypatch, provider, eligible, reason):
    from copy import deepcopy

    from services.api_core.navigation_api import _present_config

    monkeypatch.setattr(camera_pipeline_store, "snapshot", lambda: {"profile": {"analysis_location": provider}})
    result = _present_config(deepcopy(navigation_config.DEFAULT))
    assert result["behavior_catalog"]["execution_eligible"] is eligible
    assert result["behavior_catalog"]["reason"] == reason
