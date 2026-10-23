"""Transactional camera-domain changes through the existing task owner."""

from __future__ import annotations

import importlib.util
import json
import os
import time
from pathlib import Path

from common import runtime_lock
from services import camera_pipeline_store as store
from services.compute_config import _write
from services.safety_contract import request_stop

PROC_ROOT = Path("/proc")
CAPTURE_UNITS = ("camera-capture@raw.service", "camera-capture@edge.service", "camera-capture@ssd.service")

CAMERA_GOALS = ("s14_venom_navigation", "s15_venom_perception", "s12_venom_vision", "s2_camera_preview")


def _motion_active(safety):
    return safety.get("moving") or any(value != 0 for value in (safety.get("output") or {}).values())


class PipelineError(Exception):
    def __init__(self, code, status=409):
        super().__init__(code)
        self.code, self.status = code, status


def _module(name):
    try:
        return importlib.util.find_spec(name.split(".", 1)[0]) is not None
    except (ImportError, ValueError):
        return False


def capabilities():
    engines = ["canny"] if _module("cv2") else []
    ssd = Path(os.getenv("SSD_MODEL_DIR", "models/ssd"))
    if "canny" in engines and all(
        (ssd / name).is_file() for name in ("MobileNetSSD_deploy.prototxt", "MobileNetSSD_deploy.caffemodel")
    ):
        engines.append("ssd")
    if (
        "canny" in engines
        and Path(os.getenv("TFLITE_MODEL", "models/efficientdet_lite0.tflite")).is_file()
        and (_module("tflite_runtime.interpreter") or _module("tensorflow.lite"))
    ):
        engines.append("tflite")
    return {
        "analysis_locations": ["venom"] + (["local"] if engines else []),
        "local_engines": engines,
        "remote_transports": ["snapshots"] + (["mjpeg"] if _module("picamera2") else []),
        "stream_drive_supported": True,
        "local_drive_supported": False,
    }


def _runtime():
    path = store.runtime_path() / "status.json"
    try:
        if path.stat().st_size > 16384:
            raise ValueError("size")
        row = json.loads(path.read_text())
        if not isinstance(row, dict):
            raise ValueError("shape")
        pid = row.get("pid")
        if row.get("state") in {"active", "waiting_frame", "starting"}:
            if type(pid) is not int or pid <= 0:
                raise ValueError("pid")
            os.kill(pid, 0)
            age = (time.monotonic_ns() - row["observed_monotonic_ns"]) / 1_000_000_000
            if not 0 <= age <= 3:
                raise ValueError("stale")
        return row
    except (OSError, ValueError, KeyError, TypeError):
        return {"state": "stopped", "active_profile": None}


class CameraPipeline:
    def __init__(self, manager, *, capability_fn=capabilities, sleeper=time.sleep, stopper=request_stop):
        self.manager, self.capability_fn, self.sleep = manager, capability_fn, sleeper
        self.stopper = stopper

    def _legacy_status(self, profile):
        # Observe the legacy unit directly; RAM status does not exist yet.
        row = self.manager._status(self.manager.PREVIEW_UNIT)
        active = row.get("active") == "active" and not row.get("error") and row.get("stale") is not True
        state = "stopped"
        if active:
            state = "active"
        elif row.get("error") or row.get("active") == "failed":
            state = "failed"
        runtime = {"active_profile": dict(profile) if active else None}
        return active, state, runtime

    def _effective_stages(self, active, profile, use_native, legacy, tracker_active, consumers):
        return {
            "capture": active,
            "local_analysis": active and profile["analysis_location"] == "local",
            "snapshot_write": active and not use_native,
            "frame_distributor": legacy and self.manager._running("frame-distributor.service"),
            "ram_delivery": active and not legacy,
            "hardware_mjpeg": active and use_native,
            "tracker_local_analysis": active and tracker_active,
            "tracker_snapshot_write": active and tracker_active,
            "legacy_obstacle_analysis": active and "s7_obstacle_module" in consumers,
            "legacy_obstacle_snapshot_write": active and "s7_obstacle_module" in consumers,
            "remote_transport": active and profile["analysis_location"] == "venom",
        }

    def status(self, *, operation_id=None, error=None):
        config, runtime = store.snapshot(), _runtime()
        profile, state = config["profile"], runtime.get("state", "stopped")
        legacy = not store.enabled()
        active = state == "active"
        use_native = store.native(profile) and not legacy
        consumers = list(self.manager.resource_consumers().get("camera", []))
        if legacy:
            active, state, runtime = self._legacy_status(profile)
        latest = runtime.get("latest_frame")
        if latest is not None:
            latest = dict(
                latest, frame_age_ms=max(0, (time.monotonic_ns() - latest["captured_monotonic_ns"]) / 1_000_000)
            )
        tracker_active = any(
            name in {"s6_tracker_module", "s3_follow_me_face", "s3_follow_me_hand"} for name in consumers
        )
        stages = self._effective_stages(active, profile, use_native, legacy, tracker_active, consumers)
        return {
            "contract_id": "rider.camera_pipeline",
            "contract_version": 1,
            "ok": error is None,
            **config,
            "active_profile": runtime.get("active_profile") if state != "stopped" else None,
            "state": state,
            "compatibility_mode": "legacy" if legacy else None,
            "operation_id": operation_id,
            "transport_epoch": runtime.get("transport_epoch", 0),
            "camera_session": runtime.get("camera_session"),
            "capabilities": self.capability_fn(),
            "consumers": consumers,
            "effective_stages": stages,
            "latest_frame": latest,
            "capture_timestamp_source": runtime.get("capture_timestamp_source"),
            "capture_timestamp_limitation": runtime.get("capture_timestamp_limitation"),
            "error": error or runtime.get("error"),
        }

    def _idle(self):
        safety = self.manager.safety_status()
        if type(safety.get("moving")) is not bool:
            raise PipelineError("camera_pipeline_motion_status_unavailable", 503)
        if safety.get("moving") or any(value != 0 for value in (safety.get("output") or {}).values()):
            if safety.get("owner") != "navigation":
                raise PipelineError("camera_pipeline_motion_busy")
        if safety.get("error") or safety.get("stale") is True:
            raise PipelineError("camera_pipeline_motion_status_unavailable", 503)

    def _release_orphan(self):
        """Explicit OFF may recover our producer after API goal ownership is lost."""
        if not store.enabled() or self.manager.resource_consumers().get("camera", []):
            return
        runtime, config = _runtime(), store.snapshot()
        if (
            runtime.get("state") not in {"active", "waiting_frame", "starting"}
            or runtime.get("pipeline_revision") != config["revision"]
            or runtime.get("active_profile") != config["profile"]
            or not isinstance(runtime.get("camera_session"), str)
            or not runtime["camera_session"]
        ):
            return
        # The producer is a child of systemd's flock MainPID. Match its exact
        # cgroup unit, not a process name, command substring or stale goal journal.
        try:
            groups = (PROC_ROOT / str(runtime["pid"]) / "cgroup").read_text().splitlines()
        except OSError:
            return
        memberships = {part for line in groups for part in line.split(":", 2)[-1].split("/")}
        running = [unit for unit in CAPTURE_UNITS if self.manager._running(unit)]
        if len(running) != 1 or running[0] not in memberships:
            return
        unit = running[0]
        observed = self.manager._status(unit)
        if (
            observed.get("load") != "loaded"
            or observed.get("active") != "active"
            or type(observed.get("pid")) is not int
            or observed["pid"] <= 0
            or observed.get("error")
            or observed.get("stale") is True
        ):
            return
        result = self.manager.service_action(unit, "stop")
        if not result.get("ok"):
            raise PipelineError(result.get("error") or "camera_pipeline_stop_failed", 503)

    def _stop_camera_goal(self, goal, preempted):
        if preempted and goal == "s14_venom_navigation":
            result = self.manager.set_feature(
                goal,
                False,
                stop_permission=lambda _owner: {"ok": True, "confirmed": True, "permission_revoked": True},
            )
        else:
            result = self.manager.set_feature(goal, False)
        if not result.get("ok"):
            raise PipelineError(result.get("error") or "camera_pipeline_stop_failed", 503)

    def _stop(self, *, preempted=False, release_orphan=False):
        self._idle()
        consumers = self.manager.resource_consumers().get("camera", [])
        if set(consumers) - set(CAMERA_GOALS):
            raise PipelineError("camera_pipeline_foreign_consumer")
        for goal in CAMERA_GOALS:
            if goal in consumers:
                self._stop_camera_goal(goal, preempted)
        if release_orphan:
            self._release_orphan()
        # Never steal a camera opened outside this domain. A positive stop ACK
        # is insufficient: both the service and producer must have stopped.
        for unit in (*CAPTURE_UNITS, "frame-distributor.service"):
            if self.manager._running(unit):
                raise PipelineError("camera_pipeline_camera_not_released")
        safety = self.manager.safety_status()
        if safety.get("moving") or any(value != 0 for value in (safety.get("output") or {}).values()):
            raise PipelineError("camera_pipeline_stop_unconfirmed")
        if _runtime().get("state") not in {"stopped", "failed"}:
            raise PipelineError("camera_pipeline_camera_not_released")

    def _available(self, profile):
        caps = self.capability_fn()
        location = profile["analysis_location"]
        if location not in caps["analysis_locations"]:
            raise PipelineError("camera_pipeline_analysis_unavailable", 503)
        if location == "local" and profile["local_engine"] not in caps["local_engines"]:
            raise PipelineError("camera_pipeline_local_engine_unavailable", 503)
        if location == "venom" and profile["remote_transport"] not in caps["remote_transports"]:
            raise PipelineError("camera_pipeline_transport_unavailable", 503)

    def execute(self, data):
        # Serialize identical OFF retries before priority cancellation, without
        # waiting for the service lifecycle lock first.
        if isinstance(data, dict) and data.get("action") == "stop":
            admission = store.config_path().with_name("camera_pipeline_stop_admission.lock")
            with runtime_lock.exclusive(admission):
                return self._execute(data)
        return self._execute(data)

    def _configure_pipeline(self, profile, config):
        self._available(profile)
        changed = profile != config["profile"]
        if not changed and store.enabled():
            return
        selection_changed = any(profile[key] != config["profile"][key] for key in ("analysis_location", "local_engine"))
        if selection_changed:
            from apps.motion import manual_settings
            from services.perception_selection import require_idle, revoke_approval_locked

            try:
                with manual_settings.locked(blocking=False):
                    require_idle()
                    revoke_approval_locked()
                    self._configure_idle_profile(profile, config, changed)
            except (BlockingIOError, TimeoutError) as exc:
                raise PipelineError("navigation_model_selection_busy") from exc
            except ValueError as exc:
                code = str(exc)
                raise PipelineError(code, 503 if code.endswith("_unavailable") else 409) from exc
        else:
            self._configure_idle_profile(profile, config, changed)

    def _configure_idle_profile(self, profile, config, changed):
        resume_preview = bool(set(self.manager.resource_consumers().get("camera", [])) & set(CAMERA_GOALS))
        self._stop()
        config = {**config, "revision": config["revision"] + int(changed), "profile": dict(profile)}
        store.write(config)
        # Only preserve camera demand. Never recreate analysis, a
        # navigation intention, motion authority or an ARM lease.
        if resume_preview:
            result = self.manager.set_feature("s2_camera_preview", True)
            if not result.get("ok"):
                raise PipelineError(result.get("error") or "camera_pipeline_start_failed", 503)

    def _apply_pipeline_action(self, data, config, preempted):
        action = data["action"]
        if action == "configure":
            self._configure_pipeline(data["profile"], config)
        elif action == "start":
            self._available(config["profile"])
            self._idle()
            if not store.enabled():
                self._stop()
                store.write(config)
            result = self.manager.set_feature("s2_camera_preview", True)
            if not result.get("ok"):
                raise PipelineError(result.get("error") or "camera_pipeline_start_failed", 503)
        else:
            self._stop(preempted=preempted, release_orphan=True)

    def _execute(self, data):
        try:
            store.validate_request(data)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}, 400
        request_id = data["request_id"]
        preempted = False
        journal = store.config_path().with_name("camera_pipeline_requests.json")
        if data["action"] == "stop":
            response = self._admit_stop(data, journal)
            if response is not None:
                return response
        if data["action"] == "stop":
            preempted, response = self._preempt_stop(data)
            if response is not None:
                return response
        with self.manager.transaction(), runtime_lock.exclusive(journal.with_suffix(".lock")):
            return self._execute_locked(data, journal, request_id, preempted)

    def _admit_stop(self, data, journal):
        request_id = data["request_id"]
        # Read-only admission before priority cancellation. A replayed old OFF
        # or stale config must never stop a newer control session.
        try:
            prior = json.loads(journal.read_text()) if journal.exists() and journal.stat().st_size <= 131072 else []
            old = next((row for row in prior if row["request"]["request_id"] == request_id), None)
            if old is not None:
                if old["request"] != data:
                    return {
                        **self.status(operation_id=request_id, error="camera_pipeline_request_conflict"),
                        "current_revision": store.snapshot()["revision"],
                    }, 409
                return old["response"], old["status"]
        except (OSError, ValueError, KeyError, TypeError):
            return {"ok": False, "error": "camera_pipeline_journal_unavailable"}, 503
        if data["expected_revision"] != store.snapshot()["revision"]:
            return {
                **self.status(operation_id=request_id, error="camera_pipeline_revision_conflict"),
                "current_revision": store.snapshot()["revision"],
            }, 409
        return None

    def _preempt_stop(self, data):
        safety = self.manager.safety_status()
        control = safety.get("operator_control") or {}
        if safety.get("owner") != "navigation" and (_motion_active(safety)):
            return False, (self.status(operation_id=data["request_id"], error="camera_pipeline_motion_busy"), 409)
        if control.get("version") == 1 and (control.get("state") != "idle" or safety.get("state") == "DISARMED"):
            # Preempt outside the service transaction: an old cold prepare
            # holding that lock must lose its generation before a late ARM.
            generation = safety.get("generation")
            if not isinstance(generation, str) or not generation:
                return False, ({"ok": False, "error": "camera_pipeline_motion_status_unavailable"}, 503)
            result = self.stopper(owner="manual", expected_generation=generation)
            if not result.get("ok") or not result.get("confirmed"):
                return False, ({"ok": False, "error": result.get("error") or "camera_pipeline_stop_unconfirmed"}, 409)
            return True, None
        return False, None

    def _execute_locked(self, data, journal, request_id, preempted):
        entries = []
        try:
            entries = json.loads(journal.read_text()) if journal.exists() and journal.stat().st_size <= 131072 else []
            if not isinstance(entries, list):
                entries = []
            old = next((entry for entry in entries if entry["request"]["request_id"] == request_id), None)
            if old is not None:
                if old["request"] != data:
                    raise PipelineError("camera_pipeline_request_conflict")
                return old["response"], old["status"]
            config = store.snapshot()
            if data["expected_revision"] != config["revision"]:
                raise PipelineError("camera_pipeline_revision_conflict")
            self._apply_pipeline_action(data, config, preempted)
            response, status = self.status(operation_id=request_id), 200
        except PipelineError as exc:
            response, status = self.status(operation_id=request_id, error=exc.code), exc.status
            if status == 409:
                response["current_revision"] = store.snapshot()["revision"]
        except (OSError, ValueError, KeyError, TypeError):
            response, status = {"ok": False, "error": "camera_pipeline_persistence_failed"}, 503
        entries = [entry for entry in entries if entry["request"]["request_id"] != request_id][-31:]
        entries.append({"request": data, "response": response, "status": status})
        try:
            _write(journal, entries)
        except OSError:
            return {"ok": False, "error": "camera_pipeline_journal_unavailable"}, 503
        return response, status
