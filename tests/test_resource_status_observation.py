"""Read-only status with injected process and GPIO observations."""

from types import SimpleNamespace

import pytest

from services.api_core import compat, compat_health
from services.core import camera_state, lcd_state, resource_observation


@pytest.mark.parametrize("level,expected", [("0", False), ("1", True)])
def test_gpio_level_is_read_only_and_works_without_renderer_memory(monkeypatch, level, expected):
    calls = []
    monkeypatch.setattr(lcd_state, "_CACHE", None)
    monkeypatch.setattr(compat, "LAST_CAMERA", {"lcd": {}})

    def runner(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stderr="", stdout=f"GPIO 0: level={level} fsel=1 func=OUTPUT pull=NONE")

    observation = lcd_state.backlight_status(runner=runner)
    monkeypatch.setattr(lcd_state, "backlight_status", lambda: observation)
    result = compat_health.lcd_snapshot(compat, now=compat.time.time())
    assert result["on"] is expected
    assert result["confirmation"] == "gpio_level_observed"
    assert result["status_basis"] == "backlight_gpio"
    assert calls == [["raspi-gpio", "get", "0"]]


@pytest.mark.parametrize("stdout", ["", "GPIO 0: level=0 fsel=0 func=INPUT", "GPIO 0: level=9 fsel=1 func=OUTPUT"])
def test_unreadable_or_non_output_gpio_is_unknown(monkeypatch, stdout):
    monkeypatch.setattr(lcd_state, "_CACHE", None)
    result = lcd_state.backlight_status(
        runner=lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=stdout, stderr="")
    )
    assert result["on"] is None
    assert result["power_known"] is False
    assert result["error"] == "lcd_gpio_unavailable"


def test_gpio_cache_is_bounded_and_explicit_control_invalidates(monkeypatch):
    monkeypatch.setattr(lcd_state, "_CACHE", None)
    calls, tick = [], [0]

    def runner(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="GPIO 0: level=0 fsel=1 func=OUTPUT", stderr="")

    for _ in range(2):
        lcd_state.backlight_status(runner=runner, clock=lambda: tick[0])
    assert len(calls) == 1
    tick[0] = 3
    lcd_state.backlight_status(runner=runner, clock=lambda: tick[0])
    assert len(calls) == 2
    lcd_state.invalidate()
    lcd_state.backlight_status(runner=runner, clock=lambda: tick[0])
    assert len(calls) == 3


def test_camera_default_projection_reads_same_ownership_as_resource_api(monkeypatch):
    from services.api_core import resource_diag

    monkeypatch.setattr(resource_diag, "inspect", lambda name: {"free": True, "holders": [], "error": None})
    resource_observation.invalidate("camera")
    result = camera_state.snapshot(heartbeat={}, status_fn=lambda unit: {"active": "inactive", "stale": False})
    assert result["on"] is False
    assert result["service_running"] is False
    assert result["data_fresh"] is False


def test_camera_probe_failure_is_unknown(monkeypatch):
    from services.api_core import resource_diag

    monkeypatch.setattr(resource_diag, "inspect", lambda name: {"free": None, "error": "permission_denied"})
    resource_observation.invalidate("camera")
    result = camera_state.snapshot(heartbeat={}, status_fn=lambda unit: {"active": "inactive", "stale": False})
    assert result["on"] is None
    assert result["error"] == "permission_denied"


def test_read_cache_invalidates_for_state_changes():
    tick, calls = [0], []

    def probe(name):
        calls.append(name)
        return {"free": True, "holders": [], "error": None}

    resource_observation.invalidate("camera")
    for _ in range(2):
        resource_observation.snapshot("camera", probe=probe, clock=lambda: tick[0])
    assert calls == ["camera"]
    resource_observation.invalidate("camera")
    resource_observation.snapshot("camera", probe=probe, clock=lambda: tick[0])
    assert calls == ["camera", "camera"]


def test_camera_endpoints_share_off_even_without_any_heartbeat(monkeypatch, tmp_path):
    from services import api_server
    from services.api_core import features_api, resource_diag

    monkeypatch.setattr(compat, "LAST_CAMERA", {"lcd": {}})
    monkeypatch.setattr(
        resource_diag,
        "inspect",
        lambda name: {
            "free": True,
            "holders": [],
            "error": None,
            "state": "free",
            "source": "fixture",
            "observed_at": compat.time.time(),
        },
    )

    def status(unit):
        return {
            "unit": unit,
            "active": "inactive",
            "stale": False,
            "error": None,
            "installed": True,
            "source": "fixture",
            "observed_at": compat.time.time(),
        }

    monkeypatch.setattr(camera_state, "status", status)
    monkeypatch.setattr(features_api.feature_manager, "_status", status)
    monkeypatch.setattr(features_api.feature_manager, "_state_path", tmp_path / "state.json")
    monkeypatch.setattr(
        lcd_state, "backlight_status", lambda: {"on": False, "power_known": True, "observed_at": compat.time.time()}
    )
    resource_observation.invalidate("camera")
    client = api_server.app.test_client()
    health = client.get("/healthz").get_json()["devices"]["camera"]
    state = client.get("/state").get_json()["camera"]["activity"]
    catalog = client.get("/api/logic/catalog").get_json()["resource_states"]["camera"]
    resource = client.get("/api/resource/camera").get_json()["activity"]
    assert all(row["on"] is False for row in (health, state, catalog, resource))
    assert all(row["data_fresh"] is False for row in (health, state, catalog, resource))


@pytest.mark.parametrize("free,error,ttl", [(True, None, 5), (False, None, 3), (None, "unavailable", 5)])
def test_idle_resource_observations_are_shared_without_renewing_source_time(free, error, ttl):
    tick, calls = [0], []

    def probe(name):
        calls.append(name)
        return {"free": free, "error": error, "observed_at": 100, "holders": []}

    resource_observation.invalidate("camera")
    first = resource_observation.snapshot("camera", probe=probe, clock=lambda: tick[0])
    tick[0] = ttl - 0.01
    second = resource_observation.snapshot("camera", probe=probe, clock=lambda: tick[0])
    assert first == second
    assert first["observed_at"] == 100
    assert len(calls) == 1
    tick[0] = ttl
    resource_observation.snapshot("camera", probe=probe, clock=lambda: tick[0])
    assert len(calls) == 2


def test_api_policy_configures_the_existing_single_systemd_cache(monkeypatch):
    from common import systemd_snapshot
    from services.core.observation_policy import configure_systemd_observation

    monkeypatch.setattr(systemd_snapshot, "TTL_SECONDS", 0.75)
    configure_systemd_observation()
    assert systemd_snapshot.TTL_SECONDS == 2
