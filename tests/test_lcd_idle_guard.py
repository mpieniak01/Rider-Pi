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


def test_idle_guard_powers_off_when_free(monkeypatch: pytest.MonkeyPatch) -> None:
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

    assert called["release"] == 1
    lcd = guard.C.LAST_CAMERA["lcd"]
    assert lcd["on"] is False
    assert lcd["presenting"] is False
    assert lcd["auto_off_ts"] == 5.0
