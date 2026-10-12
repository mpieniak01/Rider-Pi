"""Only injected power operations; no GPIO, subprocess or robot connection."""

from services.core.lcd_cleanup import finish_lcd_stop


def test_headless_camera_stop_never_changes_lcd_power():
    calls = []
    result = finish_lcd_stop(
        "camera-capture@raw.service",
        "stop",
        {"ok": True},
        power_off=lambda: calls.append("off") or {"ok": False, "error": "lcd_owned_or_unknown"},
    )
    assert calls == []
    assert result["ok"] is True
    assert "lcd_power" not in result


def test_stopping_inactive_renderer_still_switches_panel_off():
    result = finish_lcd_stop("lcd-renderer.service", "stop", {"ok": True}, power_off=lambda: {"ok": True, "on": False})
    assert result["lcd_power"]["on"] is False


def test_renderer_stop_does_not_report_success_when_off_is_unconfirmed():
    result = finish_lcd_stop(
        "lcd-renderer.service", "stop", {"ok": True}, power_off=lambda: {"ok": False, "error": "lcd_owned_or_unknown"}
    )
    assert result["ok"] is False


def test_start_and_failed_stop_never_change_lcd_power():
    for unit, action, ok in [
        ("lcd-renderer.service", "start", True),
        ("camera-capture@raw.service", "stop", False),
        ("rider-tracker.service", "stop", True),
    ]:
        result = finish_lcd_stop(
            unit, action, {"ok": ok}, power_off=lambda: (_ for _ in ()).throw(AssertionError("unexpected GPIO"))
        )
        assert "lcd_power" not in result


def test_accepted_stop_updates_shared_lcd_observation(monkeypatch):
    from services.api_core import compat as C
    from services.api_core.compat_health import lcd_snapshot

    monkeypatch.setattr(C, "LAST_CAMERA", {"lcd": {}})
    accepted = {
        "ok": True,
        "on": False,
        "power_known": True,
        "confirmation": "control_write_accepted",
        "physical_validity": "unverified",
    }
    finish_lcd_stop("lcd-renderer.service", "stop", {"ok": True}, power_off=lambda: accepted)
    observed = lcd_snapshot(C, now=C.time.time())
    assert observed["on"] is False
    assert observed["presenting"] is False
    assert observed["source"] == "lcd-power-controller"
    assert observed["physical_validity"] == "unverified"
