"""Passive LCD projection with fake reports only; no SPI, GPIO or UART I/O."""

from copy import deepcopy

import pytest

from services.api_core import compat, compat_health, devices


@pytest.fixture
def clock(monkeypatch):
    value = [100.0]
    monkeypatch.setattr(devices.time, "time", lambda: value[0])
    monkeypatch.setattr(
        compat,
        "LAST_CAMERA",
        {"lcd": {"rot": 0, "no_draw": True, "on": None, "power_known": False}},
    )
    monkeypatch.setattr(compat, "LAST_XGO", {})
    monkeypatch.setattr(compat, "ENV_ROT", 0)
    monkeypatch.setattr(compat, "ENV_NO_DRAW", False)
    monkeypatch.setattr(compat, "ENV_DISABLE_LCD", False)
    return value


def renderer(at=100.0):
    return {
        "source": "lcd-renderer",
        "observed_at": at,
        "lcd": {
            "on": True,
            "power_known": True,
            "presenting": True,
            "rot": 270,
            "confirmation": "control_write_accepted",
            "physical_validity": "unverified",
            "reason": "status_frame",
            "frame": {
                "layout": "existing_device_info",
                "path": "/run/rider-motion/splash_device_info.png",
                "rot": 270,
                "observed_at": at,
                "confirmation": "frame_write_accepted",
                "physical_validity": "unverified",
            },
            "battery": {
                "value": 1,
                "unit": "ratio",
                "ready": True,
                "source": "motion-executor",
                "observed_at": at - 1,
            },
        },
    }


def health_lcd():
    with compat.app.test_request_context():
        return compat_health.healthz(compat).get_json()["devices"]["lcd"]


def headless(at):
    return {
        "observed_at": at,
        "source": "camera-preview",
        "mode": "preview",
        "fps": 10,
        "lcd": {"active": False, "no_draw": True, "rot": 0, "on": False},
    }


def test_renderer_frame_headless_preview_idle_and_headless_preserve_actual_state(clock):
    report = renderer()
    devices.observe_lcd(report)
    initial = health_lcd()
    assert initial["rot"] == 270 and initial["on"] is True and initial["power_known"] is True
    assert initial["source"] == initial["power_source"] == "lcd-renderer"
    assert initial["observed_at"] == initial["power_observed_at"] == 100
    assert initial["frame"] == report["lcd"]["frame"]
    assert initial["frame_source"] == "lcd-renderer" and initial["frame_observed_at"] == 100
    assert initial["battery"] == report["lcd"]["battery"]
    assert initial["confirmation"] == "control_write_accepted"
    assert initial["physical_validity"] == "unverified"
    clock[0] = 101
    devices.observe_camera_heartbeat(headless(101))
    current = health_lcd()
    for key in (
        "rot",
        "on",
        "presenting",
        "source",
        "observed_at",
        "power_observed_at",
        "frame",
        "frame_source",
        "frame_observed_at",
        "battery",
    ):
        assert current[key] == initial[key]
    assert current["preview_config"] == {
        "active": False,
        "no_draw": True,
        "rot": 0,
        "source": "camera-preview",
        "observed_at": 101,
    }
    assert current["configured_rot"] == 270 and current["configured_rot_source"] == "drivers.lcd.board"
    assert current["observed_age_s"] == 1
    assert compat.LAST_CAMERA["ts"] == 101 and compat.LAST_CAMERA["mode"] == "preview"

    clock[0] = 102
    devices.observe_lcd(
        {
            "source": "lcd-renderer",
            "observed_at": 102,
            "lcd": {
                "on": False,
                "power_known": True,
                "rot": 270,
                "confirmation": "control_write_accepted",
                "physical_validity": "unverified",
                "reason": "status_idle",
            },
        }
    )
    clock[0] = 103
    devices.observe_camera_heartbeat(headless(103))
    current = health_lcd()
    assert current["rot"] == 270 and current["on"] is False and current["power_known"] is True
    assert current["presenting"] is False and current["reason"] == "status_idle"
    assert current["observed_at"] == current["power_observed_at"] == 102
    assert current["frame"]["observed_at"] == 100 and current["battery"]["observed_at"] == 99
    assert current["frame_observed_at"] == 100 and current["frame_source"] == "lcd-renderer"
    assert current["preview_config"]["observed_at"] == 103
    assert current["configured_rot"] == 270


@pytest.mark.parametrize(
    "changes",
    [
        {"source": None},
        {"source": ""},
        {"observed_at": None, "ts": 100},
        {"observed_at": 101},
        {"observed_at": 94},
        {"observed_at": True},
        {"simulated": True},
        {"stale": True},
        {"offline": True},
        {"error": "renderer_failed"},
    ],
)
def test_invalid_or_unknown_renderer_source_does_not_replace_accepted_report(clock, changes):
    devices.observe_lcd(renderer())
    before = deepcopy(compat.LAST_CAMERA["lcd"])
    devices.observe_lcd({**renderer(), **changes})
    assert compat.LAST_CAMERA["lcd"] == before


@pytest.mark.parametrize("lcd", [{"on": False}, {"active": False, "rot": 0, "no_draw": True}])
def test_unproved_legacy_report_cannot_confirm_off_or_orientation(clock, lcd):
    devices.observe_lcd({"source": "lcd-renderer", "observed_at": 100, "lcd": lcd})
    current = health_lcd()
    assert current["on"] is None and current["power_known"] is False and current["rot"] is None


@pytest.mark.parametrize("on", [True, False])
def test_explicit_unconfirmed_gpio_keeps_accepted_frame_but_power_unknown(clock, on):
    report = renderer()
    report["lcd"].update(on=on, power_known=False)
    devices.observe_lcd(report)
    current = health_lcd()
    assert current["on"] is None and current["power_known"] is False
    assert current["power_source"] is None and current["power_observed_at"] is None
    assert current["rot"] == 270 and current["frame"] == report["lcd"]["frame"]
    assert current["presenting"] is True


def test_frame_acceptance_alone_is_not_gpio_confirmation(clock):
    report = renderer()
    report["lcd"]["confirmation"] = "frame_write_accepted"
    devices.observe_lcd(report)
    assert health_lcd()["on"] is None and health_lcd()["power_known"] is False
    assert health_lcd()["rot"] == 270


def test_out_of_order_idle_cannot_replace_current_renderer_frame(clock):
    devices.observe_lcd(renderer())
    report = renderer(99)
    report["lcd"].update(on=False, reason="status_idle")
    devices.observe_lcd(report)
    assert health_lcd()["on"] is True and health_lcd()["observed_at"] == 100


def test_unknown_preview_time_is_not_refreshed_from_receipt(clock):
    report = headless(None)
    report["ts"] = 100
    devices.observe_camera_heartbeat(report)
    assert compat.LAST_CAMERA["lcd"]["preview_config"]["observed_at"] is None
    assert compat.LAST_CAMERA["ts"] is None
    assert health_lcd()["on"] is None and health_lcd()["rot"] is None


def test_cached_bool_without_source_and_control_proof_is_unknown(clock):
    compat.LAST_CAMERA["lcd"].update(on=False, power_known=True, rot=0)
    current = health_lcd()
    assert current["on"] is None and current["power_known"] is False
    assert current["rot"] is None and current["configured_rot"] == 270


def test_accepted_power_report_without_geometry_does_not_promote_env_defaults(clock):
    devices.observe_lcd(
        {
            "source": "lcd-renderer",
            "observed_at": 100,
            "lcd": {"on": False, "power_known": True, "confirmation": "control_write_accepted"},
        }
    )
    current = health_lcd()
    assert current["on"] is False and current["rot"] is None and current["no_draw"] is None
    assert current["configured_rot"] == 270 and current["configured_no_draw"] is False
