"""Local profile files only; no UART, systemd, SDK, or live BUS."""

import copy
import json
from pathlib import Path

import pytest

from apps.motion import calibration_profiles as store
from common.motion_mapping import MAPPING_ID


@pytest.fixture
def profile(monkeypatch, tmp_path):
    monkeypatch.setenv("RIDER_CALIBRATION_DIR", str(tmp_path / "profiles"))
    record = json.loads((Path(__file__).parents[1] / "config/odometry-calibration.example.json").read_text())
    return {
        "schema_version": 1,
        "name": "Mock-only profile",
        "provenance": {"kind": "draft", "notes": ""},
        "motion": {"speed_limit": 0.4, "linear_rate": 0.8, "turn_rate": 1.2},
        "odometry": record,
        "measurements": [],
    }


def verified(profile):
    value = copy.deepcopy(profile)
    value["provenance"] = {"kind": "manual", "notes": "Fictional isolated measurement evidence"}
    value["odometry"].update(
        manual_verified=True,
        measurement_id="fake-001",
        imu_yaw_sign=1,
        linear_m_s={"1": 0.01, "-1": -0.01},
        turn_rad_s={"20": 0.02, "-20": -0.02},
    )
    value["odometry"]["conditions"] = dict.fromkeys(
        ("firmware", "surface", "load", "battery", "operator", "date"), "mock"
    )
    value["odometry"]["conditions"]["command_mapping"] = MAPPING_ID
    value["measurements"] = [{"measurement_id": "fake-001", "notes": "Fake measurement, no physical test"}]
    return value


def test_read_empty_store_does_not_create_directory_or_activate(profile):
    assert store.list_profiles() == [] and store.read_active() is None
    assert not store.storage_dir().exists()


def test_canonical_immutable_revisions_and_save_is_not_activation(profile):
    first = store.save_profile(profile)
    reordered = dict(reversed(list(profile.items())))
    second = store.save_profile(reordered)
    assert first["digest"] == second["digest"] and first["created"] and not second["created"]
    assert store.read_profile(first["digest"]) == first["profile"]
    assert store.read_active() is None
    changed = dict(profile, name="Another revision")
    assert store.save_profile(changed)["digest"] != first["digest"]
    assert len(store.list_profiles()) == 2


@pytest.mark.parametrize("kind", ["draft", "historical"])
def test_imported_and_draft_cannot_assert_verification(profile, kind):
    row = verified(profile)
    row["provenance"]["kind"] = kind
    normalized = store.validate_profile(row)
    assert normalized["odometry"]["manual_verified"] is False
    assert row["odometry"]["manual_verified"] is True  # no mutation of caller


def test_explicit_verified_record_preserves_conditions_and_evidence(profile):
    row = verified(profile)
    assert store.validate_profile(row)["odometry"]["manual_verified"] is True


@pytest.mark.parametrize(
    "edit",
    [
        lambda p: p.update(schema_version=True),
        lambda p: p.update(name=" "),
        lambda p: p.update(extra="unknown"),
        lambda p: p["motion"].update(speed_limit=True),
        lambda p: p["motion"].update(speed_limit=1.01),
        lambda p: p["motion"].update(linear_rate=101),
        lambda p: p["motion"].update(turn_rate=0),
        lambda p: p["motion"].update(turn_rate=float("inf")),
        lambda p: p["motion"].update(watchdog_s=10),
        lambda p: p["odometry"].update(manual_verified="yes"),
        lambda p: p["odometry"].update(imu_yaw_sign=True),
        lambda p: p.update(measurements=[{}] * 129),
        lambda p: p["provenance"].update(notes="a" * 4097),
        lambda p: p["odometry"].update(linear_m_s={"128": 0.1}),
        lambda p: p["odometry"].update(turn_rad_s={"0": 0.1}),
        lambda p: p["odometry"].update(turn_rad_s={"71": 0.1}),
        lambda p: p["odometry"].update(turn_rad_s={"020": 0.1}),
        lambda p: p["odometry"].update(linear_m_s={"1": -0.1}),
        lambda p: p.update(measurements=[{"duration_s": 0}]),
        lambda p: p.update(measurements=[{"duration_s": True}]),
        lambda p: p.update(measurements=[{"phase": "fiction"}]),
        lambda p: p.update(measurements=[{"outcome": "automatic_verified"}]),
        lambda p: p.update(measurements=[{"kind": "turn", "sdk_step": 0}]),
    ],
)
def test_invalid_profiles_rejected_before_storage(profile, edit):
    edit(profile)
    with pytest.raises(ValueError):
        store.save_profile(profile)
    assert not store.storage_dir().exists()


@pytest.mark.parametrize(
    "edit",
    [
        lambda p: p["odometry"]["conditions"].pop("operator"),
        lambda p: p["odometry"]["conditions"].update(date=""),
        lambda p: p["provenance"].update(notes=""),
        lambda p: p.update(measurements=[]),
        lambda p: p["measurements"][0].update(measurement_id="other"),
        lambda p: p["measurements"][0].update(notes=""),
    ],
)
def test_manual_verification_requires_local_evidence(profile, edit):
    row = verified(profile)
    edit(row)
    with pytest.raises(ValueError):
        store.validate_profile(row)


def test_nonfinite_nested_or_oversized_content_rejected(profile):
    profile["measurements"] = [{"sample": float("nan")}]
    with pytest.raises(ValueError):
        store.validate_profile(profile)
    profile["measurements"] = [{"notes": "ą" * 4000} for _ in range(9)]
    with pytest.raises(ValueError, match="oversized"):
        store.validate_profile(profile)


def test_catalog_capacity_no_overwrite_and_corruption_is_explicit(profile, monkeypatch):
    monkeypatch.setattr(store, "MAX_REVISIONS", 2)
    first = store.save_profile(profile)
    store.save_profile(dict(profile, name="Second"))
    with pytest.raises(ValueError, match="catalog_full"):
        store.save_profile(dict(profile, name="Third"))
    path = store.storage_dir() / "revisions" / (first["digest"] + ".json")
    path.write_text(json.dumps(dict(profile, name="Tampered")))
    with pytest.raises(ValueError, match="content_mismatch"):
        store.read_profile(first["digest"])


def test_bad_digest_and_duplicate_or_nonfinite_json_fail_closed(profile):
    with pytest.raises(ValueError, match="digest_invalid"):
        store.read_profile("../../credential")
    saved = store.save_profile(profile)
    path = store.storage_dir() / "revisions" / (saved["digest"] + ".json")
    for content in ('{"schema_version":1,"schema_version":1}', '{"field":NaN}'):
        path.write_text(content)
        with pytest.raises(ValueError, match="json_invalid"):
            store.read_profile(saved["digest"])


def test_executor_pointer_metadata_and_current_time(profile):
    digest = store.save_profile(profile)["digest"]
    pointer = store.write_active(digest, request_id="fake-apply", command_generation="fake-gen", seq=3, now=1000)
    assert pointer == store.read_active()
    assert pointer["activated_at"] == 1000 and pointer["request_id"] == "fake-apply"
    with pytest.raises(ValueError):
        store.write_active(digest, request_id="incomplete")


def test_staged_pointer_is_inspectable_but_never_boot_loadable(profile):
    digest = store.save_profile(profile)["digest"]
    pending = store.write_active(
        digest, request_id="r", command_generation="g", seq=1, now=1000, activation_state="pending"
    )
    assert store.read_active(include_pending=True) == pending
    with pytest.raises(ValueError, match="active_profile_pending"):
        store.read_active()
    assert store.profile_confirmation(pending, {}, {}, 1000) == "unconfirmed"
    applied = store.commit_active(digest, request_id="r", command_generation="g", seq=1)
    assert applied["activation_state"] == "applied" and applied["activated_at"] == 1000
    assert store.read_active() == applied


@pytest.mark.parametrize("changes", [{"request_id": "other"}, {"command_generation": "other"}, {"seq": 2}])
def test_commit_only_accepts_exact_pending_transaction(profile, changes):
    digest = store.save_profile(profile)["digest"]
    pending = store.write_active(
        digest, request_id="r", command_generation="g", seq=1, now=1000, activation_state="pending"
    )
    metadata = {"request_id": "r", "command_generation": "g", "seq": 1}
    metadata.update(changes)
    with pytest.raises(ValueError, match="active_profile_transaction_mismatch"):
        store.commit_active(digest, **metadata)
    assert store.read_active(include_pending=True) == pending
    with pytest.raises(ValueError, match="active_profile_pending"):
        store.read_active()


def test_commit_disk_failure_keeps_pending_for_restart(profile, monkeypatch):
    digest = store.save_profile(profile)["digest"]
    pending = store.write_active(
        digest, request_id="r", command_generation="g", seq=1, now=1000, activation_state="pending"
    )

    def failed(*_args):
        raise OSError("fake atomic write failure")

    monkeypatch.setattr(store, "_atomic", failed)
    with pytest.raises(OSError):
        store.commit_active(digest, request_id="r", command_generation="g", seq=1)
    assert store.read_active(include_pending=True) == pending
    with pytest.raises(ValueError, match="active_profile_pending"):
        store.read_active()


def test_successful_commit_has_no_fallible_temporary_cleanup(profile, monkeypatch):
    digest = store.save_profile(profile)["digest"]
    store.write_active(digest, request_id="r", command_generation="g", seq=1, now=1000, activation_state="pending")

    def forbidden_cleanup(*_args):
        raise OSError("fake cleanup failure after successful rename")

    monkeypatch.setattr(store.os, "unlink", forbidden_cleanup)
    pointer = store.commit_active(digest, request_id="r", command_generation="g", seq=1)
    assert pointer["activation_state"] == "applied" and store.read_active() == pointer


def test_unmarked_pointer_cannot_recover_precheck_rejected_profile(profile):
    digest = store.save_profile(profile)["digest"]
    pointer = store.write_active(digest, request_id="r", command_generation="g", seq=1, now=1000)
    pointer.pop("activation_state")
    (store.storage_dir() / "active.json").write_text(json.dumps(pointer))
    with pytest.raises(ValueError, match="active_profile_state_invalid"):
        store.read_active()
    assert store.profile_confirmation(pointer, {}, {}, 1000) == "unconfirmed"


def test_catalog_verification_comes_from_hashed_revision_not_editable_index(profile):
    store.save_profile(profile)
    path = store.storage_dir() / "catalog.json"
    rows = json.loads(path.read_text())
    rows[0].update(manual_verified=True, provenance={"kind": "manual"})
    path.write_text(json.dumps(rows))
    listed = store.list_profiles()[0]
    assert listed["manual_verified"] is False and listed["provenance"]["kind"] == "draft"


def test_busy_lock_fails_without_waiting(profile, monkeypatch):
    def busy(*args):
        raise BlockingIOError("fake lock busy")

    monkeypatch.setattr(store.fcntl, "flock", busy)
    with pytest.raises(BlockingIOError):
        store.save_profile(profile)
    assert not (store.storage_dir() / "active.json").exists()


def test_activation_validation_accepts_nonready_but_idle_disarmed(profile):
    row = {
        "generation": "g",
        "source": "manual",
        "seq": 2,
        "request_id": "r",
        "ts": 1000,
        "ttl_ms": 500,
        "operator_consent": True,
        "operator_plan": "No motion, fake configuration",
        "profile_digest": store.profile_digest(profile),
    }
    state = {
        "contract_version": 1,
        "state": "DISARMED",
        "moving": False,
        "ready": False,
        "observed_at": 1000,
        "generation": "g",
        "last_seq": 1,
        "target": {"lx": 0, "az": 0},
        "output": {"lx": 0, "az": 0},
    }
    assert store.validate_activate(row, state, now=1000) is None
    assert store.validate_activate(dict(row, seq=1), state, now=1000) == "activation_sequence_replayed"
    assert store.validate_activate(row, dict(state, state="ARMED"), now=1000)
    assert store.validate_activate(row, dict(state, output={"lx": 0.1, "az": 0}), now=1000)


def test_interaction_defaults_are_shared_configuration_not_motion_permission(profile):
    row = copy.deepcopy(profile)
    row["interaction"] = {"linear_speed": 0.1, "turn_speed": 0.18, "pulse_duration": 0.1}
    saved = store.save_profile(row)
    assert store.read_profile(saved["digest"])["interaction"] == row["interaction"]
    assert store.read_active() is None
    for key, invalid in [("linear_speed", True), ("turn_speed", 1.1), ("pulse_duration", 0.26)]:
        changed = copy.deepcopy(row)
        changed["interaction"][key] = invalid
        with pytest.raises(ValueError, match="interaction"):
            store.save_profile(changed)


def test_legacy_measurements_remain_inspectable_but_cannot_be_reused(profile):
    from apps.odometry.calibration import calibration_status

    row = verified(profile)
    row["odometry"]["conditions"].pop("command_mapping")
    # Read validation preserves immutable historical content and its digest.
    assert store.validate_profile(row)["odometry"]["manual_verified"] is True
    assert calibration_status(row["odometry"]) == "command_mapping_measurements_required"
    with pytest.raises(ValueError, match="command_mapping"):
        store.save_profile(row)
