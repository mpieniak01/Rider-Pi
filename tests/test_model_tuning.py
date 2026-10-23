"""Model tuning persistence and admission, using only isolated policy files."""

import math
from copy import deepcopy

import pytest

from services import navigation_config, safety_contract
from services.navigation_profiles import DEFAULT_BEHAVIOR, parameters, policy_digest
from services.perception_tuning import semantic_parameters, validate_semantic_models

SEG = "segformer-b0-ade20k"
YOLO = "yolo26n-sem-ade20k"


def stopped():
    return {
        "state": "DISARMED",
        "ready": True,
        "stale": False,
        "moving": False,
        "target": {"lx": 0, "az": 0},
        "output": {"lx": 0, "az": 0},
    }


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("RIDER_NAVIGATION_CONFIG", str(tmp_path / "navigation.json"))
    monkeypatch.setenv("FEATURE_STATE_PATH", str(tmp_path / "features.json"))
    monkeypatch.setattr(navigation_config, "_require_idle_goals", lambda: None)
    monkeypatch.setattr(navigation_config, "_require_navigation_goals_stopped", lambda: None)
    monkeypatch.setattr(safety_contract, "read_status", lambda **_: stopped())


def values():
    return {
        **deepcopy(navigation_config.DEFAULT["perception"]),
        "semantic_models": {
            SEG: {"version": 1, "surface": "floor_rug", "pixel_confidence": 0.72},
            YOLO: {"version": 1, "surface": "floor_only", "pixel_confidence": 0.85},
        },
    }


def test_save_tuning_requires_new_observation_and_preserves_models(store):
    first = navigation_config.configure(
        {
            "revision": 0,
            "values": {
                "perception": values(),
                "mode": "drive",
                "verified": True,
                "calibration_id": "forged",
                "model_sha256": "a" * 64,
            },
        }
    )
    assert first["mode"] == "observe" and first["verified"] is False
    assert first["calibration_id"] == first["model_sha256"] == ""
    assert first["perception"]["semantic_models"][SEG]["pixel_confidence"] == 0.72
    second = navigation_config.configure(
        {"revision": 1, "values": {"behavior": {**DEFAULT_BEHAVIOR, "profile_id": "fluid"}}}
    )
    assert second["perception"]["semantic_models"] == first["perception"]["semantic_models"]
    assert semantic_parameters(second["perception"], second["behavior"])["pixel_confidence"] == 0.72
    with pytest.raises(ValueError, match="conflict"):
        navigation_config.configure({"revision": 0, "values": {"perception": values()}})
    assert navigation_config.snapshot()["revision"] == 2


@pytest.mark.parametrize(
    "bad", [{"moving": True}, {"stale": True}, {"output": {"lx": 0.01, "az": 0}}, {"target": None}]
)
def test_tuning_rejects_motion_and_unknown_state(store, monkeypatch, bad):
    monkeypatch.setattr(safety_contract, "read_status", lambda **_: {**stopped(), **bad})
    with pytest.raises(ValueError, match="requires_stopped"):
        navigation_config.configure({"revision": 0, "values": {"perception": values()}})
    assert navigation_config.snapshot()["revision"] == 0


@pytest.mark.parametrize(
    "change",
    [
        {"version": True},
        {"surface": "road"},
        {"pixel_confidence": math.nan},
        {"pixel_confidence": True},
        {"min_floor_fraction": 0.1},
        {"min_region_fraction": 0.8},
    ],
)
def test_invalid_model_settings_are_rejected(store, change):
    v = values()
    v["semantic_models"][SEG].update(change)
    with pytest.raises(ValueError, match="tuning_invalid"):
        navigation_config.configure({"revision": 0, "values": {"perception": v}})
    assert navigation_config.snapshot()["revision"] == 0


def test_effective_hash_includes_active_model_configuration(store):
    base = {**DEFAULT_BEHAVIOR, "profile_id": "balanced"}
    p = values()
    assert policy_digest(base, p) != policy_digest(base)
    assert parameters(base, p)["traversable_labels"] == [3, 28]
    assert semantic_parameters(p, base)["pixel_confidence"] == 0.72


def test_config_api_presents_capability_effective_settings_and_cas(store):
    from flask import Flask

    from services.api_core.navigation_api import config_handler

    app = Flask(__name__)
    with app.test_request_context(method="POST", json={"revision": 0, "values": {"perception": values()}}):
        response, code = config_handler()
        assert code == 200
        config = response.get_json()["config"]
        assert config["model_tuning_supported"] is True
        assert config["perception_tuning"]["effective"]["traversable_labels"] == [3, 28]
    with app.test_request_context(method="GET"):
        response, code = config_handler()
        assert code == 200 and response.get_json()["revision"] == 1
    with app.test_request_context(method="POST", json={"revision": 0, "values": {"perception": values()}}):
        response, code = config_handler()
        assert code == 409


def test_empty_policy_preserves_previous_legacy_parameters():
    assert validate_semantic_models({}) == {}
    p = semantic_parameters({"engine": "segformer"})
    assert p["pixel_confidence"] == 0.8 and p["traversable_labels"] == [3]
    assert p["min_floor_fraction"] == 1


@pytest.mark.parametrize("status", [{}, {"semantic_model_policy_v1": False}, {"semantic_model_policy_v1": 1}])
def test_old_host_cannot_silently_ignore_model_settings(status):
    from apps.compute.client import ComputeError
    from apps.compute.stream_prepare import _require_model_tuning

    with pytest.raises(ComputeError, match="tuning_update_required"):
        _require_model_tuning(status, 1)
    _require_model_tuning(status, None)


def test_new_host_capability_does_not_require_any_actuation():
    from apps.compute.stream_prepare import _require_model_tuning

    _require_model_tuning({"semantic_model_policy_v1": True}, 1)


def test_depth_with_other_model_records_negotiates_new_wire_schema(monkeypatch):
    from types import SimpleNamespace

    from apps.compute import stream_prepare
    from apps.compute.navigation import NavigationRunner

    seen = []
    monkeypatch.setattr(stream_prepare, "prepare_stream", lambda **kwargs: seen.append(kwargs))
    config = deepcopy(navigation_config.DEFAULT)
    config["perception"] = {**values(), "engine": "depth_plane"}
    runner = SimpleNamespace(selection=None, policy=config, source_factory=lambda: "fixture")
    assert NavigationRunner._start_run(runner) == "fixture"
    assert seen[0]["model_tuning_version"] == 1


def test_empty_tuning_does_not_change_legacy_wire():
    from types import SimpleNamespace

    from apps.compute.navigation_cycle import NavigationCycle

    config = deepcopy(navigation_config.DEFAULT)
    config["perception"]["semantic_models"] = {}
    runner = SimpleNamespace(
        fresh_frame_seen=False,
        started=0.0,
        clock=lambda: 1.0,
        sequence=0,
        last_frame=("fixture", 1.0),
        run_id="run",
        policy=config,
        lease=SimpleNamespace(journey=None),
    )
    _, meta = NavigationCycle._frame_metadata(runner, 0.0)
    assert "semantic_models" not in meta["perception"]
    assert config["perception"]["semantic_models"] == {}


def test_legacy_hash_tracks_explicit_surface_policy():
    floor = {"engine": "segformer", "semantic_models": {SEG: {"surface": "floor_only"}}}
    rug = {"engine": "segformer", "semantic_models": {SEG: {"surface": "floor_rug"}}}
    assert policy_digest(DEFAULT_BEHAVIOR, floor) != policy_digest(DEFAULT_BEHAVIOR, rug)


def test_local_executor_disallows_new_profiles_but_allows_legacy_rollback(store, monkeypatch):
    from services import camera_pipeline_store

    monkeypatch.setattr(camera_pipeline_store, "snapshot", lambda: {"profile": {"analysis_location": "rider"}})
    with pytest.raises(ValueError, match="navigation_profile_local_executor"):
        navigation_config.configure(
            {"revision": 0, "values": {"behavior": {**DEFAULT_BEHAVIOR, "profile_id": "fluid"}}}
        )
    assert navigation_config.snapshot()["revision"] == 0
    # Existing policy can still be brought back to Legacy after provider changes.
    old = navigation_config.snapshot()
    old["behavior"] = {**DEFAULT_BEHAVIOR, "profile_id": "balanced"}
    navigation_config._write(navigation_config.path(), old)
    result = navigation_config.configure({"revision": 0, "values": {"behavior": DEFAULT_BEHAVIOR}})
    assert result["behavior"]["profile_id"] == "legacy"
    assert result["mode"] == "observe" and result["verified"] is False
