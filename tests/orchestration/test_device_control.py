"""Device aliases share the backend; fake sysfs and commands only."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from common.local_api_client import LocalAPIClient
from drivers import led
from services.api_core import face_anim, face_api, face_runtime_api, features_api
from services.core import device_control
from tests.orchestration.test_task_lifecycle import World


@pytest.fixture
def led_fixture(tmp_path, monkeypatch):
    directory = tmp_path / "leds" / "ACT"
    directory.mkdir(parents=True)
    for name, value in {
        "brightness": "0",
        "max_brightness": "1",
        "trigger": "none [mmc0] timer",
        "delay_on": "0",
        "delay_off": "0",
    }.items():
        (directory / name).write_text(value)
    monkeypatch.setenv("RIDER_LED_SYSFS", str(directory.parent))
    monkeypatch.setenv("RIDER_LED_STATE_PATH", str(tmp_path / "led-state.json"))
    manager = World().manager(tmp_path)
    monkeypatch.setattr(features_api, "feature_manager", manager)
    calls = []

    def runner(command, **kwargs):
        body = json.loads(command[-1])
        calls.append(body)
        return SimpleNamespace(returncode=0, stdout=json.dumps(led.apply(body)))

    monkeypatch.setattr(device_control.subprocess, "run", runner)
    return directory, calls


def test_led_status_does_not_change_trigger(led_fixture):
    directory, calls = led_fixture
    result = LocalAPIClient().request("/api/resource/led")["data"]
    assert result["trigger"] == "mmc0"
    assert (directory / "trigger").read_text() == "none [mmc0] timer"
    assert not calls


def test_led_actions_and_cleanup_generation_shared_across_clients(led_fixture):
    directory, calls = led_fixture
    first = LocalAPIClient().request("/api/resource/led", "POST", {"action": "blink", "on_ms": 200, "off_ms": 300})
    generation = first["data"]["generation"]
    assert first["operation"]["ack_kind"] == "control_write_accepted"
    assert first["operation"]["physical_completion"] == "unverified"
    assert (directory / "trigger").read_text() == "timer"
    second = LocalAPIClient().request("/api/resource/led", "POST", {"action": "on"})
    assert second["data"]["generation"] != generation
    from common.api_client import APIError

    with pytest.raises(APIError, match="led_session_changed"):
        LocalAPIClient().request("/api/resource/led", "POST", {"action": "off", "if_generation": generation})
    assert len(calls) == 2
    LocalAPIClient().request("/api/resource/led", "POST", {"action": "off"})
    assert (directory / "trigger").read_text() == "none"
    assert (directory / "brightness").read_text() == "0"


def test_legacy_face_lcd_uses_same_runtime(monkeypatch):
    calls = []
    monkeypatch.setattr(face_runtime_api, "play", lambda body: calls.append(body) or {"ok": True})
    assert face_api.render_face({"expr": "happy", "backend": "lcd", "rotate": 0})["ok"]
    assert calls == [{"expr": "happy", "sink": "lcd", "duration_s": 1}]


def test_invalid_face_request_never_stops_startup_lcd(monkeypatch):
    calls = []
    manager = SimpleNamespace(
        transaction=lambda: __import__("contextlib").nullcontext(), service_action=lambda *args: calls.append(args)
    )
    monkeypatch.setattr(face_runtime_api, "_manager", lambda: manager)
    assert not face_runtime_api.play({"expr": "invalid", "sink": "lcd"})["ok"]
    assert not calls


def test_file_face_preview_does_not_touch_systemd(monkeypatch):
    monkeypatch.setattr(face_runtime_api, "_manager", lambda: pytest.fail("hardware manager accessed"))
    monkeypatch.setattr(face_anim, "play", lambda body: {"ok": True, "echo": body})
    assert face_runtime_api.play({"sink": "file"})["ok"]


def test_led_auto_restores_observed_trigger_when_device_tree_is_unavailable(led_fixture):
    directory, calls = led_fixture
    client = LocalAPIClient()
    client.request("/api/resource/led", "POST", {"action": "off"})
    # A real sysfs trigger read retains the list of available choices.
    (directory / "trigger").write_text("[none] mmc0 timer")
    client.request("/api/resource/led", "POST", {"action": "auto"})
    assert (directory / "trigger").read_text() == "mmc0"
    assert calls[-1]["default_trigger"] == "mmc0"
