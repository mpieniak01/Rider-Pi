"""Camera OFF priority is tested against fake orchestration and a memory-only stop."""

from test_camera_pipeline import CAPS, Manager as BaseManager, command, isolated_paths as isolated_paths

from services.camera_pipeline import CameraPipeline


class Manager(BaseManager):
    def set_feature(self, name, enabled, *, stop_permission=None):
        if stop_permission:
            assert stop_permission("navigation")["permission_revoked"] is True
        return super().set_feature(name, enabled)


def active_manager():
    manager = Manager()
    manager.consumers = ["s14_venom_navigation", "s2_camera_preview"]
    manager.units.add(manager.PREVIEW_UNIT)
    manager.safety.update(
        state="ARMED",
        generation="running",
        owner="navigation",
        moving=True,
        output={"lx": 0.1, "az": 0},
        operator_control={"version": 1, "state": "qualifying"},
    )
    return manager


def test_off_invalidates_before_services_and_old_replay_never_stops_new_arm():
    manager = active_manager()
    stops = []

    def stop(**kwargs):
        assert manager.calls == []
        stops.append(kwargs)
        manager.safety.update(
            state="DISARMED",
            generation="stopped",
            owner=None,
            moving=False,
            output={"lx": 0, "az": 0},
            operator_control={"version": 1, "state": "idle"},
        )
        return {"ok": True, "confirmed": True}

    pipeline = CameraPipeline(manager, capability_fn=lambda: CAPS, stopper=stop)
    body, status = pipeline.execute(command("stop"))
    assert status == 200
    assert body["state"] == "stopped"
    assert stops == [{"owner": "manual", "expected_generation": "running"}]
    assert manager.calls[0] == ("s14_venom_navigation", False)
    manager.safety.update(
        state="ARMED", generation="new-arm", owner="manual", operator_control={"version": 1, "state": "paused"}
    )
    manager.calls.clear()
    assert pipeline.execute(command("stop")) == (body, status)
    assert len(stops) == 1
    assert manager.calls == []
    assert manager.safety["generation"] == "new-arm"


def test_stale_revision_and_foreign_stop_failure_do_not_run_lifecycle():
    manager = active_manager()
    stops = []

    def stop(**kwargs):
        stops.append(kwargs)
        return {"ok": False, "confirmed": False, "error": "stale_stop_generation"}

    pipeline = CameraPipeline(manager, capability_fn=lambda: CAPS, stopper=stop)
    assert pipeline.execute(command("stop", revision=999))[1] == 409
    assert stops == []
    result, status = pipeline.execute(command("stop"))
    assert status == 409
    assert result["error"] == "stale_stop_generation"
    assert manager.calls == []


def test_off_also_invalidates_pending_cold_prepare_while_disarmed():
    manager = active_manager()
    manager.safety.update(
        state="DISARMED",
        owner=None,
        moving=False,
        output={"lx": 0, "az": 0},
        operator_control={"version": 1, "state": "idle"},
    )
    stops = []

    def stop(**kwargs):
        stops.append(kwargs)
        return {"ok": True, "confirmed": True}

    pipeline = CameraPipeline(manager, capability_fn=lambda: CAPS, stopper=stop)
    assert pipeline.execute(command("stop"))[1] == 200
    assert stops == [{"owner": "manual", "expected_generation": "running"}]


def test_camera_off_does_not_stop_manual_motion_as_a_side_effect():
    manager = active_manager()
    manager.safety.update(owner="manual", operator_control={"version": 1, "state": "paused"})
    stops = []
    pipeline = CameraPipeline(
        manager,
        capability_fn=lambda: CAPS,
        stopper=lambda **kwargs: stops.append(kwargs) or {"ok": True, "confirmed": True},
    )
    body, status = pipeline.execute(command("stop"))
    assert status == 409
    assert body["error"] == "camera_pipeline_motion_busy"
    assert stops == []
    assert manager.calls == []
    assert manager.safety["moving"] is True
