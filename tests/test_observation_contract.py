"""Pure/mocked BUS and HTTP projections; no SDK/UART/systemd/network access."""

import time

import pytest

from apps.motion.sensor_quality import SensorSamples
from apps.motion.sensor_reader import project_sensor_payload
from common.observations import (
    canonical_telemetry_payload,
    legacy_xgo,
    normalize_xgo_observation,
    refresh_observation,
)
from services.api_core import compat, devices


def sensor():
    samples = SensorSamples(lambda: 20, lambda: 100, instance_id="executor")
    for name, value in {"roll": 0, "pitch": -36, "yaw": -1842358.5, "battery": 1}.items():
        samples.observe(name, value)
    return samples.payload("R-1.1.6")


def test_sole_owner_raw_bus_and_http_use_same_original_observation():
    raw = sensor()
    imu, bus = project_sensor_payload(raw, now=100)
    canonical = normalize_xgo_observation("devices.xgo", bus, now=100)
    rest = legacy_xgo(canonical)
    assert canonical_telemetry_payload({"devices": {"xgo": rest}})["devices"]["xgo"] == canonical
    rows = canonical["sensor_quality"]["sensors"]
    assert rows["battery"]["value"] == 1
    assert rows["battery"]["unit"] == "ratio"
    assert rest["battery_pct"] == 100
    assert rest["battery_unit"] == "percent"
    assert rows["yaw"]["value"] == -1842358.5
    assert rows["yaw"]["unit"] == "sdk_raw"
    assert rows["yaw"]["physical_validity"] == "unverified"
    assert rest["yaw_raw"] == rows["yaw"]["value"]
    assert rest["yaw_derivation"]["display_only"] is True
    assert rest["yaw"] == 121.5
    display = canonical["derived"]["yaw_display"]
    assert display["value"] == rest["yaw"]
    assert display["unit"] == "legacy_wrapped_degrees"
    assert display["display_only"] is True
    assert display["derivation"] == "legacy_wrap_180"
    assert display["observed_at"] == rows["yaw"]["observed_at"] == 100
    assert display["source"] == rows["yaw"]["source"]
    assert display["ready"]
    old_display = refresh_observation(canonical, now=104)["derived"]["yaw_display"]
    assert old_display["value"] == 121.5
    assert old_display["observed_at"] == 100
    assert not old_display["ready"]
    assert imu["sensor_quality"]["sensors"]["roll"]["value"] == 0
    assert "battery" not in imu["sensor_quality"]["sensors"]


@pytest.mark.parametrize(
    "topic,value,expected", [("devices.xgo", 1, 1), ("xgo", 1, 0.01), ("motion.bridge.telemetry", 1, 0.01)]
)
def test_named_battery_formats_not_magnitude_heuristics(topic, value, expected):
    row = normalize_xgo_observation(topic, {"battery_pct": value, "observed_at": 100}, now=100)
    assert row["sensor_quality"]["sensors"]["battery"]["value"] == expected
    row = normalize_xgo_observation(topic, {"battery_pct": value, "battery_unit": "volts", "observed_at": 100}, now=100)
    assert row["sensor_quality"]["sensors"]["battery"]["ready"] is False
    assert row["sensor_quality"]["sensors"]["battery"]["value"] is None


@pytest.mark.parametrize("at", [None, True, float("nan"), float("inf"), 101, 90])
def test_unknown_future_stale_source_time_never_uses_publication_time(at):
    raw = sensor()
    raw["sensor_quality"]["sensors"]["battery"]["observed_at"] = at
    raw["ts"] = 100
    row = normalize_xgo_observation("motion.sensor.raw", raw, now=100)
    battery = row["sensor_quality"]["sensors"]["battery"]
    assert not battery["ready"]
    assert battery["observed_at"] != 100


def test_per_channel_null_error_zero_and_independent_partial_battery(monkeypatch):
    raw = sensor()
    raw["sensor_quality"]["sensors"]["yaw"].update(value=None, ready=False, error="yaw_failed")
    raw["error"] = "sensor_quality:yaw"
    canonical = normalize_xgo_observation("motion.sensor.raw", raw, now=100)
    rows = canonical["sensor_quality"]["sensors"]
    assert rows["battery"]["ready"]
    assert rows["roll"]["value"] == 0
    assert not rows["yaw"]["ready"]
    assert rows["yaw"]["value"] is None
    assert not canonical["sensor_quality"]["ready"]
    assert canonical["error"] is None
    assert not canonical["stale"]
    monkeypatch.setattr(compat, "LAST_XGO", {})
    monkeypatch.setattr(devices, "normalize_xgo_observation", lambda topic, data: canonical)
    devices.observe_xgo("devices.xgo", raw)
    before = devices.xgo_snapshot(now=100)
    assert before["battery_pct"] == 100
    assert before["roll"] == 0
    assert not before["imu_ok"]
    assert before["battery_ok"]
    assert devices.xgo_snapshot(now=104)["battery_ok"] is False
    assert devices.xgo_snapshot(now=104)["battery_observed_at"] == 100


def test_new_imu_metadata_cannot_refresh_cached_battery(monkeypatch):
    monkeypatch.setattr(compat, "LAST_XGO", {})
    at = time.time()
    devices.observe_xgo("devices.xgo", {"battery_pct": 0.5, "observed_at": at})
    devices.observe_xgo(
        "imu.data", {"roll": 0, "pitch": 0, "yaw": 0, "observed_at": at + 1, "sensor_observed_at": {"battery": at + 1}}
    )
    row = devices.xgo_snapshot(now=at + 1)
    assert row["battery_observed_at"] == at
    assert row["battery_pct"] == 50


def test_parent_transport_failure_and_original_age_survive_repeated_projection():
    canonical = normalize_xgo_observation("motion.sensor.raw", sensor(), now=100)
    old = refresh_observation(canonical, now=104)
    assert old["sensor_quality"]["sensors"]["battery"]["age_s"] == 4
    assert old["sensor_quality"]["sensors"]["battery"]["observed_at"] == 100
    assert canonical["sensor_quality"]["sensors"]["battery"]["assessed_at"] == 100
    assert old["sensor_quality"]["sensors"]["battery"]["assessed_at"] == 104
    assert old["generated_at"] == canonical["generated_at"] == 100
    failed = {**canonical, "offline": True, "error": "bus_failed"}
    row = normalize_xgo_observation("devices.xgo", failed, now=100)
    assert all(not sample["ready"] for sample in row["sensor_quality"]["sensors"].values())


def test_battery_only_is_healthy_channel_but_partial_aggregate():
    row = normalize_xgo_observation("devices.xgo", {"battery_pct": 1, "observed_at": 100}, now=100)
    assert row["sensor_quality"]["sensors"]["battery"]["ready"]
    assert row["partial"]
    assert not row["sensor_quality"]["ready"]


def test_simulated_channel_is_diagnostic_value_not_physical_ready():
    row = normalize_xgo_observation("devices.xgo", {"battery_pct": 1, "observed_at": 100, "simulated": True}, now=100)
    battery = row["sensor_quality"]["sensors"]["battery"]
    assert battery["value"] == 1
    assert battery["simulated"]
    assert not battery["ready"]
    assert row["partial"]


def test_simulated_executor_labels_raw_bus_samples_before_projection():
    samples = SensorSamples(lambda: 20, lambda: 100, instance_id="simulation", simulated=True)
    for name in ("roll", "pitch", "yaw", "battery"):
        samples.observe(name, 0)
    raw = samples.payload()
    assert raw["simulated"]
    _, bus = project_sensor_payload(raw, now=100)
    rows = bus["sensor_quality"]["sensors"]
    assert all(row["simulated"] and not row["ready"] for row in rows.values())
    assert bus["partial"]


@pytest.mark.parametrize("version", [True, "1", 0, 2, None])
def test_declared_unknown_contract_is_not_interpreted_as_legacy(version):
    row = normalize_xgo_observation(
        "devices.xgo",
        {"contract_id": "rider.telemetry", "contract_version": version, "battery_pct": 1, "observed_at": 100},
        now=100,
    )
    assert row["error"] == "unsupported_telemetry_contract"
    assert row["partial"]
    assert not row["sensor_quality"]["sensors"]


def test_canonical_sample_requires_explicit_unit_even_with_legacy_fallback():
    raw = sensor()
    raw["sensor_quality"]["sensors"]["battery"].pop("unit")
    raw["battery_unit"] = "ratio"
    row = normalize_xgo_observation("motion.sensor.raw", raw, now=100)["sensor_quality"]["sensors"]["battery"]
    assert row["value"] is None
    assert not row["ready"]
    assert row["error"] == "measurement_unit_unknown"


def test_idle_vision_cannot_mark_battery_observation_transport_stale(monkeypatch):
    from services.api_core import state_api

    monkeypatch.setattr(compat, "LAST_XGO", {})
    monkeypatch.setattr(compat, "LAST_STATE", {"ts": None, "stale": True, "error": "vision_not_started"})
    now = time.time()
    devices.observe_xgo("devices.xgo", {"battery_pct": 1, "observed_at": now})
    body = state_api.state().get_json()
    assert body["vision"]["state"]["stale"]
    assert body["vision"]["state"]["error"] == "vision_not_started"
    assert not body.get("stale")
    assert not body.get("offline")
    assert not body.get("error")
    assert body["devices"]["xgo"]["observation"]["sensor_quality"]["sensors"]["battery"]["ready"]
    assert body["partial"]
