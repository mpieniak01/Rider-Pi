from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from common.service_catalog import (
    BASE_UNITS,
    CAMERA_UNITS,
    DEFAULT_REGISTRY,
    PROTECTED_UNITS,
    UNIT_CATALOG,
    catalog_payload,
    task_units,
)
from services.core.features import FeatureManager, NullPublisher


class World:
    def __init__(self):
        self.active = {*BASE_UNITS, "rider-core.target"}
        self.missing = set()
        self.unknown = set()
        self.fail = set()
        self.actions = []
        self.safety = {
            "ready": True,
            "can_move": True,
            "owner": "follow_me",
            "generation": "operator-generation",
            "capabilities": {action: {"available": True, "stop_verified": True} for action in ("move", "turn")},
        }
        self.stop_confirmed = True
        self.seq = 0

    def status(self, unit):
        return {
            "unit": unit,
            "load": "not-found" if unit in self.missing else "loaded",
            "active": "active" if unit in self.active else "inactive",
            "sub": "running",
            "error": "unknown" if unit in self.unknown else None,
        }

    def run(self, unit, action):
        self.actions.append((unit, action))
        ok = (unit, action) not in self.fail
        if ok and action == "start":
            self.active.add(unit)
        elif ok and action == "stop":
            self.active.discard(unit)
        return {"unit": unit, "action": action, "ok": ok}

    def stop(self, owner):
        self.actions.append(("control", "stop"))
        self.safety.update(
            ready=False, can_move=False, owner=None, generation=self.safety.get("generation", "") + ".stopped"
        )
        return {"ok": self.stop_confirmed, "confirmed": self.stop_confirmed}

    def manager(self, tmp_path):
        manager = FeatureManager(
            runner=self.run,
            status_fn=self.status,
            publisher=NullPublisher(),
            safety_status=lambda: self.safety,
            safety_stop=self.stop,
            dependency_check=lambda *args: [],
            state_path=tmp_path / "state.json",
        )
        manager.producer_status = lambda unit: {
            "unit": unit,
            "accepted": True,
            "active": True,
            "observed_at": time.time(),
            "generation": self.safety.get("generation"),
            "request_id": manager._service_intents().get(unit, {}).get("request_id"),
            "domains": ["asr", "tts", "chat"],
            "capabilities": {domain: {"ready": True, "model_loaded": True} for domain in ("asr", "tts", "chat")},
        }
        original = manager.set_feature

        def explicit_fake_intent(name, enabled, options=None, control=None):
            self.seq += 1
            envelope = {
                "generation": self.safety.get("generation"),
                "source": "manual",
                "seq": self.seq,
                "ts": time.time(),
                "ttl_ms": 500,
                "request_id": f"fake-{self.seq}",
            }
            return original(name, enabled, options=options, control=envelope if control is None else control)

        manager.set_feature = explicit_fake_intent
        return manager


def test_two_consumers_keep_camera_until_last_stop(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    assert manager.set_feature("s2_camera_preview", True)["ok"]
    assert manager.set_feature("s6_tracker_module", True)["ok"]
    assert manager.resource_consumers()["camera"] == ["s2_camera_preview", "s6_tracker_module"]
    assert manager.set_feature("s2_camera_preview", False)["ok"]
    assert set(CAMERA_UNITS) <= world.active
    assert manager.set_feature("s6_tracker_module", False)["ok"]
    assert not set(CAMERA_UNITS) & world.active
    assert set(BASE_UNITS) <= world.active


def test_passive_tracker_never_starts_controller_or_publishes_motion(tmp_path):
    world = World()
    world.safety = {"ready": False, "can_move": False, "owner": None}
    manager = world.manager(tmp_path)
    assert manager.set_feature("s6_tracker_module", True)["ok"]
    assert "rider-tracking-controller.service" not in world.active
    assert manager.publisher.sent == [("tracking.mode:set", {"mode": "face"})]
    row = next(row for row in manager.describe_features() if row["name"] == "s6_tracker_module")
    assert row["ready"]
    assert row["can_move"] is False


@pytest.mark.parametrize("owner", [None, "manual", "navigation"])
def test_moving_task_requires_matching_operator_owner(tmp_path, owner):
    world = World()
    world.safety["owner"] = owner
    result = world.manager(tmp_path).set_feature("face_tracking", True)
    assert result["error"] == "operator_motion_permission_required"
    assert world.actions == []


def test_stop_confirmed_before_releasing_autonomy(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    assert manager.set_feature("face_tracking", True)["ok"]
    world.actions.clear()
    assert manager.set_feature("face_tracking", False)["ok"]
    assert world.actions[0] == ("control", "stop")
    assert all(unit not in PROTECTED_UNITS for unit, action in world.actions if action == "stop")


def test_unconfirmed_stop_keeps_all_resources(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    assert manager.set_feature("face_tracking", True)["ok"]
    before = set(world.active)
    world.stop_confirmed = False
    world.actions.clear()
    result = manager.set_feature("face_tracking", False)
    assert result["error"] == "stop_unconfirmed"
    assert world.active == before
    assert world.actions == [("control", "stop")]


@pytest.mark.parametrize("failure", ["missing", "unknown"])
def test_members_not_target_determine_availability(tmp_path, failure):
    world = World()
    getattr(world, failure).add("rider-tracker.service")
    world.active.add("rider-tracker.target")
    manager = world.manager(tmp_path)
    result = manager.set_feature("s6_tracker_module", True)
    assert result["ok"] is False
    assert world.actions == []
    row = next(row for row in manager.describe_features() if row["name"] == "s6_tracker_module")
    assert row["installed"] is False
    assert row["ready"] is False


def test_partial_start_rolls_back_only_new_unshared_services(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    assert manager.set_feature("s2_camera_preview", True)["ok"]
    world.fail.add(("rider-tracker.service", "start"))
    result = manager.set_feature("s6_tracker_module", True)
    assert result["ok"] is False
    assert set(CAMERA_UNITS) <= world.active


def test_failed_rollback_is_partial_and_can_be_stopped(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    world.fail.update({("rider-tracker.service", "start"), (CAMERA_UNITS[0], "stop")})
    result = manager.set_feature("s6_tracker_module", True)
    assert result["state"] == "partial"
    world.fail.clear()
    assert manager.set_feature("s6_tracker_module", False)["ok"]
    assert CAMERA_UNITS[0] not in world.active


def test_external_camera_is_never_released_by_task(tmp_path):
    world = World()
    world.active.update(CAMERA_UNITS)
    manager = world.manager(tmp_path)
    assert manager.set_feature("s6_tracker_module", True)["ok"]
    assert manager.set_feature("s6_tracker_module", False)["ok"]
    assert set(CAMERA_UNITS) <= world.active
    assert "external" in manager.unit_consumers(CAMERA_UNITS[0])


def test_start_is_serialized_and_idempotent(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: manager.set_feature("s6_tracker_module", True), range(8)))
    assert all(result["ok"] for result in results)
    assert world.actions.count((CAMERA_UNITS[0], "start")) == 1
    assert world.actions.count(("rider-tracker.service", "start")) == 1


def test_camera_and_follow_mode_conflicts_deny_without_stealing(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    assert manager.set_feature("face_tracking", True)["ok"]
    before = list(world.actions)
    assert manager.set_feature("hand_tracking", True)["error"] == "resource_conflict"
    assert manager.set_feature("s11_dev_mode", True)["error"] == "resource_conflict"
    assert world.actions == before


def test_administration_cannot_stop_shared_camera(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    assert manager.set_feature("s6_tracker_module", True)["ok"]
    result = manager.service_action(CAMERA_UNITS[0], "stop")
    assert result["error"] == "resource_in_use"


def test_restart_does_not_restore_requested_motion(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    assert manager.set_feature("face_tracking", True)["ok"]
    replacement = world.manager(tmp_path)
    row = next(row for row in replacement.describe_features() if row["name"] == "s3_follow_me_face")
    assert row["running"] is True
    assert row["requested"] is False
    assert row["ready"] is False


def test_s0_and_s1_distinguish_permission_not_process(tmp_path):
    world = World()
    world.safety = {"ready": True, "can_move": False, "state": "DISARMED"}
    rows = {row["name"]: row for row in world.manager(tmp_path).describe_features()}
    assert rows["s0_core"]["ready"] is True
    assert rows["s1_manual"]["running"] is True
    assert rows["s1_manual"]["ready"] is False


def test_catalog_alternative_profiles_are_minimal():
    obstacle = DEFAULT_REGISTRY["s7_obstacle_module"]
    assert "rider-vision-offload.service" not in task_units(obstacle)
    remote = task_units(obstacle, {"provider": "pc"})
    assert "rider-vision-offload.service" in remote
    assert "rider-vision.service" not in remote
    assert "rider-obstacle.service" not in remote
    voice = DEFAULT_REGISTRY["s5_voice"]
    assert "rider-voice-web.service" in task_units(voice, {"domain": "asr"})
    assert "rider-voice.service" not in task_units(voice, {"domain": "asr"})
    assert "rider-google-bridge.service" not in task_units(voice)
    dev = DEFAULT_REGISTRY["s11_dev_mode"]
    assert not {"graphical.target", "jupyter.service", "camera-capture@ssd.service"} & set(task_units(dev))


@pytest.mark.parametrize(
    "task,options",
    [
        ("s11_dev_mode", {"tool": "jupyter"}),
        ("s5_voice", {"domain": "vision"}),
        ("s7_obstacle_module", {"provider": "typo"}),
        ("s6_tracker_module", {"provider": "pc"}),
    ],
)
def test_unknown_options_never_fall_back(task, options):
    with pytest.raises(ValueError):
        task_units(DEFAULT_REGISTRY[task], options)


@pytest.mark.parametrize("capability", [{}, {"supported": True}, {"available": True, "stop_verified": False}])
def test_unverified_actuator_capability_refuses_task_without_actions(tmp_path, capability):
    world = World()
    world.safety["capabilities"]["move"] = capability
    result = world.manager(tmp_path).set_feature("face_tracking", True)
    assert result["error"] == "actuator_capability_unavailable"
    assert world.actions == []


def test_one_catalog_all_members_and_stable_motion_traits():
    catalog = catalog_payload()
    assert catalog["contract_version"] == 2
    for feature in DEFAULT_REGISTRY.values():
        assert set(task_units(feature)) <= set(UNIT_CATALOG)
    assert UNIT_CATALOG["motion-executor.service"]["resources"] == ["uart"]
    assert UNIT_CATALOG["sensor-reader.service"]["resources"] == []


def test_manual_jupyter_and_no_optional_autostart(tmp_path):
    world = World()
    world.active.add("jupyter.service")
    manager = world.manager(tmp_path)
    assert manager.set_feature("s11_dev_mode", True)["ok"]
    assert manager.set_feature("s11_dev_mode", False)["ok"]
    assert "jupyter.service" in world.active
    assert manager.service_action("jupyter.service", "enable")["ok"] is False


def test_get_can_observe_starting_during_slow_fake_action(tmp_path):
    world = World()
    original = world.run
    entered, release = Event(), Event()

    def delayed(unit, action):
        if unit == CAMERA_UNITS[0] and action == "start":
            entered.set()
            assert release.wait(2)
        return original(unit, action)

    world.run = delayed
    manager = world.manager(tmp_path)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(manager.set_feature, "s6_tracker_module", True)
        assert entered.wait(2)
        row = next(row for row in manager.describe_features() if row["name"] == "s6_tracker_module")
        assert row["requested"]
        assert row["state"] == "starting"
        assert not row["ready"]
        catalog_row = next(row for row in manager.catalog()["features"] if row["name"] == "s6_tracker_module")
        assert catalog_row["state"] == "starting"
        state_row = next(row for row in manager.state_snapshot()["features"] if row["name"] == "s6_tracker_module")
        assert state_row["state"] == "starting"
        release.set()
        assert future.result()["ok"]


def test_baseline_active_processes_do_not_mask_unknown_executor(tmp_path):
    world = World()
    world.safety = {"state": "UNKNOWN", "ready": False, "can_move": False, "stale": True}
    manager = world.manager(tmp_path)
    row = next(row for row in manager.describe_features() if row["name"] == "s0_core")
    assert row["running"]
    assert not row["ready"]
    assert row["state"] == "partial"
    assert row["error"] == "baseline_executor_unavailable"


def test_operation_reuses_unit_observations_but_not_safety_or_generation(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    status_calls = []
    safety_calls = []
    elapsed = [0.0]

    def status(unit):
        status_calls.append(unit)
        elapsed[0] += 0.025
        return world.status(unit)

    def safety():
        safety_calls.append(world.safety["generation"])
        return dict(world.safety)

    manager.status_fn, manager.safety_status = status, safety
    unit = "motion-executor.service"
    manager._status(unit)
    manager._status(unit)
    assert len(status_calls) == 2  # Unchanged behavior outside an operation.
    with manager.operation(guard=lambda: None, remaining=lambda: 5.0, stop=world.stop):
        first = manager._status(unit)
        first["active"] = "tampered"
        for _ in range(20):
            assert manager._status(unit)["active"] == "active"
        assert len(status_calls) == 3
        assert elapsed[0] == pytest.approx(0.075)
        feature = DEFAULT_REGISTRY["s3_follow_me_face"]
        assert manager._permission(feature) is None
        world.safety.update(owner=None, generation="new-operator-generation")
        assert manager._permission(feature)["error"] == "operator_motion_permission_required"
        denied = manager._intent_permission(
            {
                "source": "manual",
                "generation": "operator-generation",
                "seq": 1,
                "ts": time.time(),
                "ttl_ms": 500,
                "request_id": "obsolete",
            }
        )
        assert denied["error"] == "stale_or_invalid_operator_intent"
        assert len(safety_calls) == 3
    assert manager._operation_status_cache is None
    world.active.discard(unit)
    assert manager._status(unit)["active"] == "inactive"
    manager._status(unit)
    assert len(status_calls) == 5


@pytest.mark.parametrize("action", ["start", "stop"])
@pytest.mark.parametrize("failure", [None, "result", "exception"])
def test_every_operation_action_invalidates_all_unit_statuses_even_on_failure(tmp_path, action, failure):
    world = World()
    manager = world.manager(tmp_path)
    unit, dependency = "rider-tracker.service", "camera-capture@raw.service"
    if action == "stop":
        world.active.update((unit, dependency))
    calls = []

    def observed(name):
        calls.append(name)
        return world.status(name)

    def run(name, requested):
        # A target can affect other members, even before an error is returned.
        for changed in (name, dependency):
            if requested == "start":
                world.active.add(changed)
            else:
                world.active.discard(changed)
        if failure == "exception":
            raise RuntimeError("partial fixture failure")
        return {"ok": failure is None, "unit": name, "action": requested}

    manager.status_fn, manager.runner = observed, run
    with manager.operation(guard=lambda: None, remaining=lambda: 5.0, stop=world.stop):
        before = "active" if action == "stop" else "inactive"
        assert manager._status(unit)["active"] == before
        assert manager._status(dependency)["active"] == before
        assert len(calls) == 2
        result = manager._run(unit, action)
        assert result["ok"] is (failure is None)
        after = "active" if action == "start" else "inactive"
        assert manager._status(unit)["active"] == after
        assert manager._status(dependency)["active"] == after
        assert len(calls) == 4
        manager._status(dependency)
        assert len(calls) == 4


def test_exception_leaving_operation_discards_observation_cache(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    unit = "rider-tracker.service"
    # Catch outside operation so cancellation exercises its error-exit cleanup.
    with pytest.raises(RuntimeError, match="cancel operation"):
        with manager.operation(guard=lambda: None, remaining=lambda: 5.0, stop=world.stop):
            assert manager._status(unit)["active"] == "inactive"
            raise RuntimeError("cancel operation")
    world.active.add(unit)
    assert manager._operation_status_cache is None
    assert manager._status(unit)["active"] == "active"
