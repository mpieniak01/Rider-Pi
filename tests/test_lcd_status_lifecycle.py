"""LCD lifecycle tests use fake displays, inventory, clock and command runner."""

from types import SimpleNamespace

import pytest

from apps.ui.lcd_power import off_if_free
from apps.ui.status_panel import StatusPanelLifecycle, battery_observation, battery_text, ownership_permits


class Sink:
    def __init__(self):
        self.frames = []
        self.closed = False
        self.rotate = 270

    def display(self, *args, **kwargs):
        self.frames.append((args, kwargs))

    def close(self):
        self.closed = True


def lifecycle():
    clock = SimpleNamespace(now=0)
    sinks, off, reports = [], [], []
    ownership = {"free": True, "holders": [], "error": None}

    def create():
        sink = Sink()
        sinks.append(sink)
        return sink

    def power_off():
        off.append(True)
        return True

    panel = StatusPanelLifecycle(
        sink_factory=create,
        owner_probe=lambda: ownership,
        power_off=power_off,
        report=lambda **fields: reports.append(fields),
        clock=lambda: clock.now,
        idle_s=10,
    )
    return panel, clock, sinks, off, reports, ownership


def test_status_zero_battery_and_unknown_never_fabricate():
    assert battery_text({"ready": True, "value": 0}) == "Battery: 0%"
    assert "brak" in battery_text({"ready": False, "value": 1})
    good = {"value": 0, "unit": "ratio", "ready": True, "observed_at": 100}
    status = {
        "contract_version": 1,
        "instance_id": "executor",
        "state": "ESTOP",
        "observed_at": 100,
        "error": "sensor_quality:yaw",
        "sensor_quality": {"sensors": {"battery": good}},
    }
    assert battery_observation(status, now=101)["ready"] is True
    old = battery_observation(status, now=103)
    assert old["ready"] is False and old["observed_at"] == 100
    good["observed_at"] = None
    assert not battery_observation(status, now=100)["ready"]
    good["observed_at"] = 100
    status["offline"] = True
    assert not battery_observation(status, now=100)["ready"]


@pytest.mark.parametrize(
    "changes",
    [
        {"simulated": True},
        {"observed_at": 101},
        {"observed_at": None},
        {"instance_id": None},
        {"contract_version": 0},
        {"contract_version": True},
        {"error": "uart_timeout"},
    ],
)
def test_lcd_unknown_future_or_simulated_executor_cannot_supply_battery(changes):
    status = {
        "contract_version": 1,
        "instance_id": "executor",
        "observed_at": 100,
        "sensor_quality": {"sensors": {"battery": {"value": 1, "unit": "ratio", "ready": True, "observed_at": 100}}},
        **changes,
    }
    assert not battery_observation(status, now=100)["ready"]


@pytest.mark.parametrize("changes", [{"simulated": True}, {"source": "demo"}, {"instance_id": "other"}])
def test_lcd_battery_channel_must_belong_to_real_current_executor(changes):
    status = {
        "contract_version": 1,
        "instance_id": "executor",
        "observed_at": 100,
        "sensor_quality": {
            "sensors": {"battery": {"value": 1, "unit": "ratio", "ready": True, "observed_at": 100, **changes}}
        },
    }
    assert not battery_observation(status, now=100)["ready"]


def test_malformed_task_journal_is_only_unknown_empty_status():
    panel, _, _, _, _, _ = lifecycle()
    assert panel.step({"requested": None, "active": 1, "features": None}, {"ready": False}, "", []) == "presenting"


@pytest.mark.parametrize("features", [None, 1, [None, 2, {"name": "voice", "services": [None, 1]}]])
def test_lcd_summary_accepts_unknown_journal_rows_without_hardware(features):
    from scripts.lcd_renderer import summarize_state

    title, lines, _ = summarize_state({"active": ["voice"], "features": features, "ts": "unknown"})
    assert title == "Zadania (ostatni zapis)" and lines


def test_frame_without_gpio_confirmation_keeps_power_unknown():
    panel, _, _, _, reports, _ = lifecycle()
    panel.step({}, {"ready": False}, "", [])
    assert reports[-1]["on"] is None and not reports[-1]["power_known"] and reports[-1]["presenting"]


def test_battery_and_heartbeat_changes_do_not_keep_light_on():
    panel, clock, sinks, off, reports, _ = lifecycle()
    state = {"active": [], "features": [], "ts": 1}
    panel.step(state, {"ready": False}, "Stan 0", [])
    clock.now = 4
    panel.step({**state, "ts": 2}, {"ready": True, "value": 1}, "Stan 0", [])
    assert len(sinks[0].frames) == 2  # late first real source is displayed
    clock.now = 10
    assert panel.step({**state, "ts": 3}, {"ready": True, "value": 0.9}, "Stan 0", []) == "idle_off"
    assert off == [True] and sinks[0].closed
    clock.now = 50
    panel.step(state, {"ready": True, "value": 0.8}, "Stan 0", [])
    assert off == [True] and len(sinks) == 1
    assert reports[-1]["on"] is False
    assert reports[-1]["rot"] == 270


def test_meaningful_task_change_wakes_but_cannot_take_another_owner():
    panel, clock, sinks, off, _, ownership = lifecycle()
    panel.step({}, {"ready": False}, "Stan 0", [])
    clock.now = 10
    panel.step({}, {"ready": False}, "Stan 0", [])
    task = {"requested": ["voice"], "features": [{"name": "voice", "state": "starting"}]}
    clock.now = 12
    assert panel.step(task, {"ready": False}, "Zadania", []) == "presenting"
    assert len(sinks) == 2
    ownership.update(free=False, holders=[{"pid": 9999999}])
    task["features"][0]["state"] = "ready"
    assert panel.step(task, {"ready": False}, "Zadania", []) == "ownership_unknown_or_external"
    assert sinks[-1].closed and len(sinks) == 2 and off == [True]
    assert panel.close() is False and off == [True]


@pytest.mark.parametrize(
    "inventory", [{}, {"free": None}, {"free": True, "error": "unreadable"}, {"free": False, "holders": [{"pid": 42}]}]
)
def test_unknown_or_external_owner_never_initializes_or_powers_off(inventory):
    panel = StatusPanelLifecycle(
        sink_factory=lambda: pytest.fail("no display I/O"),
        owner_probe=lambda: inventory,
        power_off=lambda: pytest.fail("no power I/O"),
    )
    assert panel.step({}, {"ready": False}, "", []) == "ownership_unknown_or_external"
    assert not panel.close()


def test_known_self_descriptor_is_allowed_but_power_helper_needs_free(monkeypatch):
    assert ownership_permits({"free": False, "holders": [{"pid": 5}]}, pid=5)
    monkeypatch.setattr("apps.ui.status_panel.os.getpid", lambda: 5)
    result = off_if_free(
        probe=lambda: {"free": False, "holders": [{"pid": 5}]},
        runner=lambda *args, **kwargs: pytest.fail("self descriptor is still open"),
    )
    assert result["on"] is None


def test_power_off_uses_installed_xgo_gpio_zero_without_reset(monkeypatch):
    monkeypatch.delenv("FACE_LCD_BL_PIN", raising=False)
    monkeypatch.setattr("apps.ui.lcd_power.os.geteuid", lambda: 1000)
    commands = []

    def run(command, **kwargs):
        commands.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    result = off_if_free(probe=lambda: {"free": True, "holders": []}, runner=run)
    command, options = commands[0]
    assert command[:2] == ["sudo", "-n"]
    assert command[-5:] == ["off", "--bl", "0", "--rst", "-1"]
    assert options["timeout"] == 3 and options["check"] is False
    assert result["on"] is False and result["physical_validity"] == "unverified"
    assert result["confirmation"] == "control_write_accepted"


def test_failed_power_off_never_claims_physical_off():
    result = off_if_free(
        probe=lambda: {"free": True, "holders": []}, runner=lambda *args, **kwargs: SimpleNamespace(returncode=1)
    )
    assert not result["ok"] and result["on"] is None and not result["power_known"]


def test_legacy_stopped_and_old_v1_never_look_like_current_motion():
    from apps.ui.motion_status import display_motion, number_label

    assert display_motion({"stopped": True, "output": {"lx": 0, "az": 0}}, now=100)["state"] == "UNKNOWN"
    row = {"contract_version": 1, "state": "ESTOP", "observed_at": 100, "moving": False, "output": {"lx": 0, "az": 0}}
    current = display_motion(row, now=101)
    assert current["moving"] is False and current["output"]["lx"] == 0
    assert current["physical_completion"] == "unverified" and not current["can_move"]
    assert display_motion(row, now=104)["moving"] is None
    assert number_label(None) == "—" and number_label(0) == "0.00"
