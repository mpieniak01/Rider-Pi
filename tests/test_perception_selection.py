"""Safe selection uses real file CAS and locks; all motor calls stay in memory."""

import copy
import json
import threading

import pytest
from flask import Flask
from motion_fakes import command, executor as executor

from apps.compute.decision_lease import DecisionLease
from apps.motion import manual_settings
from services import navigation_config as config, perception_selection as selection
from services.api_core import navigation_api, rider_routes
from services.core.goal_journal import boot_id


@pytest.fixture
def idle(tmp_path, monkeypatch):
    monkeypatch.setenv("RIDER_NAVIGATION_CONFIG", str(tmp_path / "navigation.json"))
    monkeypatch.setenv("FEATURE_STATE_PATH", str(tmp_path / "features.json"))
    monkeypatch.setenv("RIDER_MANUAL_SETTINGS_PATH", str(tmp_path / "settings.json"))
    state = {
        "requested": [],
        "active": [],
        "ownership_journal": {"boot_id": boot_id(), "admin": []},
    }
    path = tmp_path / "features.json"
    path.write_text(json.dumps(state))
    safety = {
        "state": "DISARMED",
        "ready": True,
        "stale": False,
        "owner": None,
        "can_move": False,
        "moving": False,
        "active_source": None,
        "generation": "idle",
        "target": {"lx": 0, "az": 0},
        "output": {"lx": 0, "az": 0},
    }
    monkeypatch.setattr(selection, "read_status", lambda **kw: copy.deepcopy(safety))
    monkeypatch.setattr("services.safety_contract.read_status", lambda **kw: copy.deepcopy(safety))
    return safety, state, path


def choice(model="depth-anything-v2-indoor-small", revision=0, sha="a"):
    return {
        "model_id": model,
        "artifact_sha256": sha * 64,
        "engine": selection.MODEL_ENGINES[model],
        "revision": revision,
    }


def accepted():
    row = copy.deepcopy(config.DEFAULT)
    row.update(mode="drive", verified=True, calibration_id="accepted", model_sha256="b" * 64)
    row["perception"]["engine"] = "depth_plane"
    row["avoidance"].update(enabled=True, sweep_verified=True, protocol_version=2)
    row["avoidance"]["geometry"]["mode"] = "image"
    config.path().write_text(json.dumps(row))
    return row


def test_selection_clears_all_acceptance_and_preserves_camera_journal(idle):
    accepted()
    before = idle[2].read_bytes()
    selected = selection.select(choice("segformer-b0-ade20k"))
    assert selected["revision"] == 1
    assert selected["mode"] == "observe"
    assert not selected["verified"]
    assert selected["model_sha256"] == selected["calibration_id"] == ""
    assert selected["avoidance"]["sweep_verified"] is False
    assert selected["avoidance"]["enabled"] is False
    assert selected["perception"]["model_id"] == "segformer-b0-ade20k"
    assert selected["perception"]["artifact_sha256"] == "a" * 64
    assert config.snapshot() == selected
    assert idle[2].read_bytes() == before


def test_legacy_config_is_unchanged_on_read_and_existing_approved_drive_is_valid(idle):
    baseline = accepted()
    before = config.path().read_bytes()
    assert config.snapshot() == baseline
    assert config.path().read_bytes() == before
    assert "model_id" not in config.snapshot()["perception"]


def test_ack_lost_replay_and_stale_other_choice(idle):
    initial = selection.select(choice())
    assert selection.select(choice()) == initial
    assert selection.select(choice(revision=1)) == initial
    with pytest.raises(ValueError, match="configuration_conflict"):
        selection.select(choice("fast-scnn-floor"))
    assert config.snapshot() == initial


def test_replay_does_not_restore_acceptance_after_new_config(idle):
    selected = selection.select(choice())
    config.configure(
        {
            "revision": selected["revision"],
            "values": {"mode": "drive", "verified": True, "calibration_id": "new", "model_sha256": "a" * 64},
        }
    )
    with pytest.raises(ValueError, match="configuration_conflict"):
        selection.select(choice())
    assert config.snapshot()["mode"] == "drive"


@pytest.mark.parametrize(
    "patch",
    [
        {"state": "ARMED"},
        {"owner": "manual"},
        {"owner": "navigation"},
        {"stale": True},
        {"ready": False},
        {"moving": True},
        {"can_move": True},
        {"state": "UNKNOWN"},
        {"moving": None},
        {"output": {"lx": 0.001, "az": 0}},
        {"target": {}},
        {"generation": None},
        {"active_source": "manual"},
    ],
)
def test_active_or_unknown_executor_never_changes_config(idle, patch):
    idle[0].update(patch)
    with pytest.raises(ValueError, match="requires_idle_disarmed"):
        selection.select(choice())
    assert not config.path().exists()


@pytest.mark.parametrize(
    "field,name",
    [
        ("requested", "s14_venom_navigation"),
        ("active", "s15_venom_perception"),
        ("requested", "s3_follow_me_face"),
    ],
)
def test_active_or_requested_loop_and_local_movement_are_blocked(idle, field, name):
    idle[1][field] = [name]
    idle[2].write_text(json.dumps(idle[1]))
    with pytest.raises(ValueError, match="stop_loops_first"):
        selection.select(choice())
    assert not config.path().exists()


def test_camera_only_goal_may_remain_running(idle):
    idle[1]["requested"] = idle[1]["active"] = ["s2_camera_preview"]
    idle[2].write_text(json.dumps(idle[1]))
    assert selection.select(choice())["mode"] == "observe"


@pytest.mark.parametrize("state", [None, {}, {"requested": [], "active": []}])
def test_missing_or_foreign_boot_journal_is_unknown(idle, state):
    if state is None:
        idle[2].unlink()
    else:
        idle[2].write_text(json.dumps(state))
    with pytest.raises(ValueError, match="goal_state_unavailable"):
        selection.select(choice())


@pytest.mark.parametrize(
    "patch",
    [
        {"model_id": []},
        {"artifact_sha256": "bad"},
        {"artifact_sha256": ""},
        {"engine": "segformer"},
        {"revision": True},
        {"revision": -1},
        {"unknown": "http://elsewhere"},
    ],
)
def test_invalid_selection_has_no_persistence(idle, patch):
    with pytest.raises(ValueError):
        selection.select(dict(choice(), **patch))
    assert not config.path().exists()


def test_ordinary_config_cannot_bypass_host_selection_or_remove_explicit_identity(idle):
    explicit = dict(config.DEFAULT["perception"], **{k: v for k, v in choice().items() if k != "revision"})
    with pytest.raises(ValueError, match="selection_required"):
        config.configure({"revision": 0, "values": {"perception": explicit}})
    selection.select(choice())
    with pytest.raises(ValueError, match="selection_required"):
        config.configure({"revision": 1, "values": {"perception": dict(config.DEFAULT["perception"])}})
    assert config.snapshot()["revision"] == 1


def test_legacy_engine_change_uses_guard_and_revokes_in_same_write(idle):
    accepted()
    changed = dict(config.DEFAULT["perception"])
    row = config.configure(
        {
            "revision": 0,
            "values": {
                "perception": changed,
                "avoidance": copy.deepcopy(config.DEFAULT["avoidance"]),
                "mode": "drive",
                "verified": True,
                "calibration_id": "new",
                "model_sha256": "c" * 64,
            },
        }
    )
    assert row["mode"] == "observe"
    assert not row["verified"]
    assert row["model_sha256"] == row["calibration_id"] == ""
    idle[0]["state"] = "ARMED"
    with pytest.raises(ValueError, match="requires_idle_disarmed"):
        config.configure({"revision": 1, "values": {"perception": dict(changed, engine="depth_plane")}})


@pytest.mark.parametrize("model", ["segformer-b0-ade20k", "fast-scnn-floor", "yolo26n-sem-ade20k"])
def test_explicit_semantic_models_are_observe_only_in_config_and_final_lease(idle, model):
    row = selection.select(choice(model))
    invalid = dict(row, mode="drive", verified=True, calibration_id="new", model_sha256="a" * 64)
    with pytest.raises(ValueError, match="model_observe_only"):
        config.validate(invalid)
    calls = []
    lease = DecisionLease(
        invalid, "run", lambda *a: calls.append("MOVE"), lambda: calls.append("STOP"), clock=lambda: 1
    )
    decision = {
        "protocol_version": 1,
        "run_id": "run",
        "frame_id": "f",
        "sequence": 1,
        "config_revision": row["revision"],
        "model_sha256": "a" * 64,
        "action": "go",
        "model_id": model,
        "artifact_sha256": "a" * 64,
        "valid_for_ms": 150,
        "clear_count": 3,
        "state": "clear",
    }
    assert not lease.accept(decision, "f", 1, 1)
    assert calls == ["STOP"]
    assert lease.reason == "navigation_model_observe_only"


def test_explicit_depth_approval_must_match_selected_artifact(idle):
    row = selection.select(choice())
    with pytest.raises(ValueError, match="approval_mismatch"):
        config.validate(dict(row, mode="drive", verified=True, calibration_id="new", model_sha256="b" * 64))


def test_real_executor_rejects_concurrent_arm_but_stop_bypasses_selection_mutex(idle, executor, monkeypatch):
    instance, _ = executor
    arm = command(instance, "arm", owner="manual", operator_consent=True, operator_plan="Inert fixture", lease_s=10)
    acknowledgements = []
    original = selection._write

    def during_write(*args):
        # Another thread has the exact execution mutex used by real ARM.
        worker = threading.Thread(target=lambda: acknowledgements.append(instance.apply(arm)))
        worker.start()
        worker.join(timeout=1)
        assert not worker.is_alive()
        assert instance.gate.state == "DISARMED"
        # Urgent STOP remains usable while this same lock is held.
        assert instance.apply({"action": "stop", "source": "manual"})["status"] == "executed"
        original(*args)

    monkeypatch.setattr(selection, "_write", during_write)
    selection.select(choice())
    assert acknowledgements[0]["status"] == "rejected"
    assert "busy" in acknowledgements[0]["reason"]


def test_selection_rejects_busy_executor_mutex_without_waiting(idle):
    entered, release = threading.Event(), threading.Event()

    def hold():
        with manual_settings.locked():
            entered.set()
            release.wait(timeout=2)

    worker = threading.Thread(target=hold)
    worker.start()
    assert entered.wait(1)
    try:
        with pytest.raises(BlockingIOError):
            selection.select(choice())
    finally:
        release.set()
        worker.join(timeout=2)


def test_http_identity_commit_returns_current_config_and_cache_is_disabled(idle):
    app = Flask(__name__)
    rider_routes.register_compute(app)
    with app.test_client() as http:
        response = http.post("/api/navigation/model-selection", json=choice())
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert response.json["config"]["perception"]["model_id"] == choice()["model_id"]
        assert http.post("/api/navigation/model-selection", json=choice("fast-scnn-floor")).status_code == 409
