"""Local profile files only; no UART, systemd, SDK, or live BUS."""

import copy
import json
from pathlib import Path

import pytest

from apps.motion import calibration_profiles as store


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
        lambda p: p["odometry"].update(linear_m_s={"13": 0.1}),
        lambda p: p["odometry"].update(turn_rad_s={"19": 0.1}),
        lambda p: p["odometry"].update(turn_rad_s={"71": 0.1}),
        lambda p: p["odometry"].update(turn_rad_s={"020": 0.1}),
        lambda p: p["odometry"].update(linear_m_s={"1": -0.1}),
        lambda p: p.update(measurements=[{"duration_s": 0}]),
        lambda p: p.update(measurements=[{"duration_s": True}]),
        lambda p: p.update(measurements=[{"phase": "fiction"}]),
        lambda p: p.update(measurements=[{"outcome": "automatic_verified"}]),
        lambda p: p.update(measurements=[{"kind": "turn", "sdk_step": 1}]),
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
