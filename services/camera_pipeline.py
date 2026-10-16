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

CAMERA_GOALS = ("s14_venom_navigation", "s15_venom_perception", "s12_venom_vision", "s2_camera_preview")


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
    def __init__(self, manager, *, capability_fn=capabilities, sleeper=time.sleep):
        self.manager, self.capability_fn, self.sleep = manager, capability_fn, sleeper

    def status(self, *, operation_id=None, error=None):
        config, runtime = store.snapshot(), _runtime()
        profile, state = config["profile"], runtime.get("state", "stopped")
        legacy = not store.enabled()
        active = state == "active"
        use_native = store.native(profile) and not legacy
        consumers = list(self.manager.resource_consumers().get("camera", []))
        if legacy:
            # Observe the legacy unit directly; RAM status does not exist yet.
            row = self.manager._status(self.manager.PREVIEW_UNIT)
            active = row.get("active") == "active" and not row.get("error") and row.get("stale") is not True
            state = "active" if active else "failed" if row.get("error") or row.get("active") == "failed" else "stopped"
            runtime = {"active_profile": dict(profile) if active else None}
        latest = runtime.get("latest_frame")
        if latest is not None:
            latest = dict(
                latest, frame_age_ms=max(0, (time.monotonic_ns() - latest["captured_monotonic_ns"]) / 1_000_000)
            )
        tracker_active = any(
            name in {"s6_tracker_module", "s3_follow_me_face", "s3_follow_me_hand"} for name in consumers
        )
        stages = {
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

    def _stop(self):
        self._idle()
        consumers = self.manager.resource_consumers().get("camera", [])
        if set(consumers) - set(CAMERA_GOALS):
            raise PipelineError("camera_pipeline_foreign_consumer")
        for goal in CAMERA_GOALS:
            if goal in consumers:
                result = self.manager.set_feature(goal, False)
                if not result.get("ok"):
                    raise PipelineError(result.get("error") or "camera_pipeline_stop_failed", 503)
        # Never steal a camera opened outside this domain.
        for unit in (
            "camera-capture@raw.service",
            "camera-capture@edge.service",
            "camera-capture@ssd.service",
            "frame-distributor.service",
        ):
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
        try:
            store.validate_request(data)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}, 400
        request_id = data["request_id"]
        journal = store.config_path().with_name("camera_pipeline_requests.json")
        with self.manager.transaction(), runtime_lock.exclusive(journal.with_suffix(".lock")):
            entries = []
            try:
                entries = (
                    json.loads(journal.read_text()) if journal.exists() and journal.stat().st_size <= 131072 else []
                )
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
                action = data["action"]
                if action == "configure":
                    profile = data["profile"]
                    self._available(profile)
                    changed = profile != config["profile"]
                    if changed or not store.enabled():
                        resume_preview = bool(
                            set(self.manager.resource_consumers().get("camera", [])) & set(CAMERA_GOALS)
                        )
                        self._stop()
                        config = {**config, "revision": config["revision"] + int(changed), "profile": dict(profile)}
                        store.write(config)
                        # Only preserve camera demand. Never recreate analysis, a
                        # navigation intention, motion authority or an ARM lease.
                        if resume_preview:
                            result = self.manager.set_feature("s2_camera_preview", True)
                            if not result.get("ok"):
                                raise PipelineError(result.get("error") or "camera_pipeline_start_failed", 503)
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
                    self._stop()
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
