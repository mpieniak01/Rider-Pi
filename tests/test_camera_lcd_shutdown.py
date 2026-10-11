"""Camera shutdown fixtures never import camera hardware or open the robot bus."""

from __future__ import annotations

import signal
import sys
from types import SimpleNamespace

import pytest

from apps.camera import capture_service
from apps.camera.lcd_shutdown import close_preview_lcd
from apps.ui.lcd_power import off_if_free


def test_preview_releases_own_spi_before_power_probe_and_cleans_once():
    calls = []
    module = SimpleNamespace(
        disp=SimpleNamespace(SPI=SimpleNamespace(close=lambda: calls.append("close"))), LCD_ok=True
    )

    def off():
        calls.append("probe_then_off")
        assert module.disp is None
        return {"ok": True}

    assert close_preview_lcd(module, power_off=off) == {"ok": True}
    assert close_preview_lcd(module, power_off=off) is None
    assert calls == ["close", "probe_then_off"]
    assert module.LCD_ok is False


def test_headless_stop_does_not_change_lcd_power():
    calls = []
    assert close_preview_lcd(SimpleNamespace(disp=None), power_off=lambda: calls.append("off")) is None
    assert calls == []


@pytest.mark.parametrize(
    "snapshot",
    [
        {"free": False, "holders": [{"pid": 999}], "error": None},
        {"free": None, "holders": [], "error": "lsof_failed"},
    ],
)
def test_other_owner_and_failed_inventory_never_send_lcd_off(snapshot):
    calls = []
    module = SimpleNamespace(disp=SimpleNamespace(SPI=SimpleNamespace(close=lambda: calls.append("close"))))
    result = close_preview_lcd(
        module, power_off=lambda: off_if_free(probe=lambda: snapshot, runner=lambda *a, **k: calls.append("off"))
    )
    assert result["ok"] is False
    assert calls == ["close"]


def test_sigterm_unwinds_mode_and_restores_previous_handler(monkeypatch):
    previous = object()
    handlers = []
    cleaned = []
    module = SimpleNamespace()
    monkeypatch.setenv("CAPTURE_MODE", "raw")
    monkeypatch.setitem(sys.modules, "apps.camera.preview_lcd", module)
    monkeypatch.setattr(signal, "getsignal", lambda signum: previous)
    monkeypatch.setattr(signal, "signal", lambda signum, handler: handlers.append(handler))
    monkeypatch.setattr(capture_service, "close_preview_lcd", cleaned.append)

    def run(cfg):
        handlers[0](signal.SIGTERM, None)

    monkeypatch.setattr(capture_service, "_run_mode", run)
    assert capture_service.main() == 0
    assert cleaned == [module]
    assert handlers[-1] is previous


def test_startup_failure_still_releases_preview_lcd(monkeypatch):
    module = SimpleNamespace()
    cleaned = []
    monkeypatch.setenv("CAPTURE_MODE", "raw")
    monkeypatch.setitem(sys.modules, "apps.camera.preview_lcd", module)
    monkeypatch.setattr(capture_service, "close_preview_lcd", cleaned.append)
    monkeypatch.setattr(capture_service, "_run_mode", lambda cfg: (_ for _ in ()).throw(RuntimeError("capture failed")))
    assert capture_service.main() == 1
    assert cleaned == [module]
