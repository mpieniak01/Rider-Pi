from __future__ import annotations

import importlib

import pytest


def _reload_guard(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LCD_IDLE_GUARD", "1")
    monkeypatch.setenv("LCD_IDLE_OFF_AFTER_S", "1")
    monkeypatch.setenv("LCD_IDLE_CHECK_INTERVAL", "0.1")
    import services.lcd_idle_guard as guard

    return importlib.reload(guard)


def _base_lcd_state():
    return {
        "enabled_env": True,
        "no_draw": False,
        "rot": 0,
        "active": False,
        "on": True,
        "presenting": False,
        "holders": [],
        "checked_at": None,
        "auto_off_ts": None,
    }


def test_idle_guard_skips_when_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    guard = _reload_guard(monkeypatch)
    monkeypatch.setattr(guard.C, "LAST_CAMERA", {"lcd": _base_lcd_state()})

    called = {"release": 0}

    def fake_inspect(name: str):
        return {"free": False, "holders": [{"pid": 123}], "checked_at": 5.0}

    def fake_release(name: str):
        called["release"] += 1
        return {"ok": True}

    monkeypatch.setattr(guard.resource_diag, "inspect", fake_inspect)
    monkeypatch.setattr(guard.resource_diag, "release", fake_release)

    guard._last_busy_ts = 0.0
    guard._last_action_ts = 0.0
    guard._power_state = None

    guard._poll_once(now=5.0)

    assert called["release"] == 0
    lcd = guard.C.LAST_CAMERA["lcd"]
    assert lcd["on"] is True
    assert lcd["presenting"] is True
    assert lcd["holders"]


def test_idle_guard_free_resource_requires_explicit_operator_action(monkeypatch: pytest.MonkeyPatch) -> None:
    guard = _reload_guard(monkeypatch)
    monkeypatch.setattr(guard.C, "LAST_CAMERA", {"lcd": _base_lcd_state()})

    called = {"release": 0}

    def fake_inspect(name: str):
        return {"free": True, "holders": [], "checked_at": 5.0}

    def fake_release(name: str):
        called["release"] += 1
        return {"ok": True}

    monkeypatch.setattr(guard.resource_diag, "inspect", fake_inspect)
    monkeypatch.setattr(guard.resource_diag, "release", fake_release)

    guard._last_busy_ts = 0.0
    guard._last_action_ts = 0.0
    guard._power_state = None

    guard._poll_once(now=5.0)

    assert called["release"] == 0
    lcd = guard.C.LAST_CAMERA["lcd"]
    assert lcd["on"] is True
    assert lcd["presenting"] is False
    assert lcd["auto_off_ts"] is None
    assert lcd["idle_release_requires_operator"] is True


@pytest.mark.parametrize(
    "snapshot",
    [
        {"free": None, "state": "unknown", "error": "permission denied"},
        {"free": None, "state": "unavailable", "error": None},
        {"free": False, "state": "unknown", "error": "partial inventory"},
    ],
)
def test_unknown_ownership_cannot_fabricate_power_or_release(monkeypatch, snapshot):
    guard = _reload_guard(monkeypatch)
    monkeypatch.setattr(guard.C, "LAST_CAMERA", {"lcd": _base_lcd_state()})
    monkeypatch.setattr(guard.resource_diag, "inspect", lambda _: snapshot)
    monkeypatch.setattr(guard.resource_diag, "release", lambda _: pytest.fail("automatic release forbidden"))
    guard._poll_once(now=100.0)
    lcd = guard.C.LAST_CAMERA["lcd"]
    assert lcd["on"] is None and lcd["presenting"] is None and lcd["power_known"] is False
    with guard.C.app.test_request_context():
        status = guard.C.healthz().get_json()["devices"]["lcd"]
    assert status["on"] is None and status["power_known"] is False


@pytest.mark.parametrize("free", [True, False])
def test_recovered_ownership_does_not_infer_power_from_configuration(monkeypatch, free):
    guard = _reload_guard(monkeypatch)
    monkeypatch.setattr(guard.C, "LAST_CAMERA", {"lcd": _base_lcd_state()})
    monkeypatch.setattr(guard.C, "ENV_DISABLE_LCD", False)
    monkeypatch.setattr(guard.C, "ENV_NO_DRAW", False)
    guard._update_lcd_state(snapshot={"free": None, "state": "unknown", "error": "temporary"})
    guard._update_lcd_state(snapshot={"free": free, "state": "free" if free else "busy"})
    lcd = guard.C.LAST_CAMERA["lcd"]
    assert lcd["presenting"] is (not free) and lcd["on"] is None and lcd["power_known"] is False
    with guard.C.app.test_request_context():
        status = guard.C.healthz().get_json()["devices"]["lcd"]
    assert status["on"] is None and not status["power_known"] and status["configured_on"]


@pytest.mark.parametrize("on", [False, True])
def test_explicit_renderer_power_report_recovers_unknown_state(monkeypatch, on):
    from services.api_core import devices

    guard = _reload_guard(monkeypatch)
    monkeypatch.setattr(guard.C, "LAST_CAMERA", {"lcd": _base_lcd_state()})
    monkeypatch.setattr(devices.time, "time", lambda: 123.0)
    guard._update_lcd_state(snapshot={"free": None, "error": "temporary"})
    devices.observe_lcd({"ts": 123.0, "lcd": {"active": True}})
    assert guard.C.LAST_CAMERA["lcd"]["on"] is None
    devices.observe_lcd(
        {
            "source": "lcd-renderer",
            "observed_at": 123.0,
            "lcd": {"on": on, "power_known": True, "confirmation": "control_write_accepted"},
        }
    )
    with guard.C.app.test_request_context():
        status = guard.C.healthz().get_json()["devices"]["lcd"]
    assert status["on"] is on and status["power_known"]
    assert guard.C.LAST_CAMERA["lcd"]["power_observed_at"] == 123.0


def test_initial_lcd_unknown_has_no_env_power_fallback(monkeypatch):
    guard = _reload_guard(monkeypatch)
    monkeypatch.setattr(guard.C, "LAST_CAMERA", {"lcd": {}})
    monkeypatch.setattr(guard.C, "ENV_DISABLE_LCD", False)
    monkeypatch.setattr(guard.C, "ENV_NO_DRAW", False)
    with guard.C.app.test_request_context():
        status = guard.C.healthz().get_json()["devices"]["lcd"]
    assert status["on"] is None and status["power_known"] is False
