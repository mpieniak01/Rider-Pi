"""Only injected power operations; no GPIO, subprocess or robot connection."""

from services.core.lcd_cleanup import finish_lcd_stop


def test_camera_stop_calls_full_off_after_runner_and_preserves_other_owner():
    calls = []
    result = finish_lcd_stop(
        "camera-capture@raw.service",
        "stop",
        {"ok": True},
        power_off=lambda: calls.append("off") or {"ok": False, "error": "lcd_owned_or_unknown"},
    )
    assert calls == ["off"]
    assert result["ok"] is True
    assert result["lcd_power"]["error"] == "lcd_owned_or_unknown"


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
