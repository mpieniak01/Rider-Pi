"""Pi transport and bounded actuation; visual inference runs only on Venom."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import signal
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from collections import deque

from apps.compute.client import ComputeError
from apps.compute.decision_lease import DecisionLease
from apps.compute.runners import FrameSource, selected_executor
from apps.safety.intent import read_service_intent, write_intent_status
from common.bus import BusPub
from services import navigation_config
from services.control_commands import submit_control
from services.safety_contract import read_status

UNIT = "rider-venom-navigation.service"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise ComputeError("navigation_redirect_denied")


class NavigationRunner:
    def __init__(
        self,
        *,
        source_factory=FrameSource,
        request=None,
        clock=time.monotonic,
        observe_only=False,
        publisher_factory=None,
    ):
        self.source_factory = source_factory
        self.publisher_factory = publisher_factory or (lambda: BusPub(warmup_ms=50))
        self.motion_publisher = None
        self.motion_started = False
        self.turn_capture_after = None
        self.pending_motion_acks = {}
        self.request = request or self._request
        self.clock = clock
        self.startup_deadline = clock() + 5.0
        self.closed = threading.Event()
        self.saved_policy = navigation_config.snapshot()
        self.policy = {**self.saved_policy, "mode": "observe"} if observe_only else self.saved_policy
        self.last_result = None
        self.decision_trace = deque(maxlen=12)
        self.frame_trace = deque(maxlen=4)
        self.motion_failure = None
        self.request_roundtrip_ms = None
        self.response_age_ms = None
        self.run_started_monotonic = None
        self.cycle_started = clock()
        self.cycle_timings_ms = {}
        self.previous_status_write_ms = None
        self.selection = selected_executor()
        if not self.selection:
            raise ComputeError("compute_executor_not_selected")
        self.run_id = uuid.uuid4().hex
        self.sequence = 0
        self.motion_sequence = -1
        self.intent = None
        self.generation = None
        self.settings_revision = None
        self.calibration_digest = None
        self.last_frame = None
        self.fresh_frame_seen = False
        self.lease = DecisionLease(
            self.policy,
            self.run_id,
            self.drive,
            self.stop,
            clock,
            pause=self.pause,
            feedback_wait=self.policy["mode"] == "drive",
            turn=self.turn,
            steer=self.steer,
        )
        self.started = clock()

    def _timed(self, phase, callback, *args, **kwargs):
        started = self.clock()
        try:
            return callback(*args, **kwargs)
        finally:
            self.cycle_timings_ms[phase] = round((self.clock() - started) * 1000, 2)

    def _authority(self):
        safety = self._timed("safety_read_ms", read_status)
        if self.policy["mode"] == "observe":
            return False
        if (
            safety.get("remote_decision_deadline_supported") is not True
            or safety.get("remote_decision_feedback_supported") is not True
            or safety.get("scoped_stop_generation_supported") is not True
        ):
            raise ComputeError("navigation_executor_update_required")
        if self._consent_completed(safety):
            raise ComputeError("navigation_trial_completed")
        for ack in [safety.get("last_ack") or {}, *(safety.get("recent_acks") or [])]:
            if (
                isinstance(ack.get("request_id"), str)
                and ack["request_id"].startswith(self.run_id + "-")
                and ack.get("status") == "rejected"
            ):
                self.motion_failure = {
                    "http_status": 409,
                    "reason": ack.get("error") or ack.get("reason") or "executor_rejected",
                    "gate_reason": safety.get("reason"),
                }
                raise ComputeError("navigation_motion_rejected")
        acknowledgements = [safety.get("last_ack") or {}, *(safety.get("recent_acks") or [])]
        for request_id, deadline in list(self.pending_motion_acks.items()):
            ack = next((row for row in acknowledgements if row.get("request_id") == request_id), None)
            if ack and ack.get("status") == "executed" and ack.get("accepted") is True:
                del self.pending_motion_acks[request_id]
            elif self.clock() >= deadline:
                self.motion_failure = {"http_status": 504, "reason": "navigation_motion_ack_timeout"}
                raise ComputeError("navigation_motion_ack_timeout")
        intent = self._timed("intent_read_ms", read_service_intent, UNIT, safety.get("generation"))
        if (
            safety.get("can_move") is not True
            or safety.get("owner") != "navigation"
            or not intent
            or (self.generation and self.generation != safety.get("generation"))
        ):
            raise ComputeError("navigation_authority_lost")
        if self.intent and self.intent["request_id"] != intent["request_id"]:
            raise ComputeError("navigation_intent_changed")
        settings = safety.get("manual_settings") or {}
        revision = settings.get("revision")
        if type(revision) is not int or intent.get("settings_revision") != revision:
            raise ComputeError("navigation_settings_stale")
        digest = (safety.get("calibration") or {}).get("profile_digest")
        if self.settings_revision is not None and (
            revision != self.settings_revision or digest != self.calibration_digest
        ):
            raise ComputeError("navigation_calibration_changed")
        self.settings_revision, self.calibration_digest = revision, digest
        self.intent = intent
        self.generation = safety["generation"]
        self.motion_sequence = max(self.motion_sequence, safety.get("last_seq", -1), intent["seq"])
        if not self._timed(
            "producer_claim_ms",
            write_intent_status,
            UNIT,
            intent,
            active=True,
            data_ready=self.lease.deadline is not None,
            navigation_ready=self.lease.deadline is not None,
        ):
            raise ComputeError("navigation_producer_claim_failed")
        return True

    def drive(self, speed, duration, *, yaw=0.0):
        self._timed("authority_ms", self._authority)
        if self.lease.deadline is not None and self.clock() >= self.lease.deadline:
            self.motion_failure = {"http_status": 409, "reason": "navigation_decision_expired_before_submit"}
            raise ComputeError("navigation_decision_expired_before_submit")
        self.motion_sequence += 1
        result, code = self._timed(
            "submit_ms",
            submit_control,
            {
                "action": "move",
                "source": "navigation",
                "execution_context": "panel",
                "generation": self.generation,
                "seq": self.motion_sequence,
                "request_id": self.run_id + "-" + str(self.motion_sequence),
                "ts": time.time(),
                "ttl_ms": 100,
                "settings_revision": self.settings_revision,
                "decision_deadline_monotonic": self.lease.deadline,
                "decision_feedback_deadline_monotonic": self.lease.feedback_deadline,
                "vx": speed,
                "yaw": yaw,
                "duration": duration,
            },
            **({"publisher": self.motion_publisher, "timeout_s": 0.0} if self.motion_publisher is not None else {}),
        )
        if (code == 200 and result.get("ok")) or (code == 202 and result.get("pending")):
            self.motion_started = self.motion_started or speed != 0 or yaw != 0
        if code == 202 and result.get("pending"):
            self.pending_motion_acks[self.run_id + "-" + str(self.motion_sequence)] = self.clock() + 0.1
        if not (code == 200 and result.get("ok") or code == 202 and result.get("pending")):
            if self._consent_completed(result.get("safety") or {}):
                raise ComputeError("navigation_trial_completed")
            error = result.get("error") or (result.get("ack") or {}).get("reason")
            if not isinstance(error, str) or not error.replace("_", "").isalnum() or len(error) > 128:
                error = "executor_rejected"
            self.motion_failure = {"http_status": code, "reason": error}
            gate_reason = (result.get("safety") or {}).get("reason")
            if isinstance(gate_reason, str):
                self.motion_failure["gate_reason"] = gate_reason
            logging.getLogger(__name__).warning("[vision] motion rejected status=%s reason=%s", code, error)
            raise ComputeError("navigation_motion_rejected")

    def turn(self, side, duration):
        settings = self.policy["avoidance"]
        if side not in {"left", "right"} or not settings["enabled"] or not settings["sweep_verified"]:
            raise ComputeError("navigation_avoidance_not_accepted")
        self.drive(0.0, duration, yaw=settings["turn_speed"] * (1 if side == "left" else -1))
        # Actuation cannot outlive the Pi-local permit. Require a capture after
        # that bound and settling, not merely a reply received after the turn.
        self.turn_capture_after = self.lease.deadline + 0.1

    def steer(self, side, duration):
        settings = self.policy["avoidance"]
        if (
            side not in {"left", "right"}
            or not settings["enabled"]
            or not settings["sweep_verified"]
            or settings["protocol_version"] != 3
        ):
            raise ComputeError("navigation_avoidance_not_accepted")
        self.drive(self.policy["speed"], duration, yaw=settings["turn_speed"] * (1 if side == "left" else -1))
        # Re-evaluate after this bounded correction; never reuse a capture
        # from before/during it to issue another correction or forward goal.
        # Submission may return pending before the executor applies the pulse.
        # Its output is bounded by the lease; capture after that bound and settling.
        self.turn_capture_after = self.lease.deadline + 0.1

    def _consent_completed(self, safety):
        return (
            self.generation is not None
            and safety.get("state") == "DISARMED"
            and safety.get("reason") == "consent_expired"
        )

    def pause(self, duration):
        self.drive(0.0, duration)

    def stop(self):
        if self.policy["mode"] != "drive":
            return
        safety = read_status()
        if safety.get("owner") != "navigation" or safety.get("generation") != self.generation:
            return
        _, code = submit_control(
            {
                "action": "stop",
                "source": "navigation",
                "owner": "navigation",
                "request_id": self.run_id + "-stop",
                "expected_generation": self.generation,
            }
        )
        if code not in {200, 202}:
            self.closed.set()

    def _request(self, meta, payload, mime):
        base = self.selection["url"].rstrip("/")
        if not base.endswith("/api/v1/rider/compute"):
            base += "/api/v1/rider/compute"
        reference = payload if isinstance(payload, dict) else None
        if reference is not None:
            payload = json.dumps({"frame": meta, "source": reference}).encode()
            mime = "application/json"
        req = urllib.request.Request(
            base + ("/vision/decision-reference" if reference is not None else "/vision/decision"),
            data=payload,
            headers={
                "Content-Type": mime,
                "X-Rider-Device": self.selection["device_id"],
                "Authorization": "Bearer " + self.selection["token"],
                "X-Rider-Vision": json.dumps(meta),
            },
        )
        timeout = self.policy["decision_budget_ms"] / 1000
        if self.policy["mode"] == "observe":
            # Observation cannot actuate; Wi-Fi jitter must not become a drive permit.
            timeout = max(1.0, timeout)
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=timeout) as response:
            body = response.read(16385)
            if len(body) > 16384:
                raise ComputeError("navigation_response_bounds")
            decision = json.loads(body)
            if reference is not None and decision.get("source") != reference:
                raise ComputeError("navigation_reference_mismatch")
            return decision

    def _startup_retry(self):
        return self.policy["mode"] == "drive" and not self.motion_started and self.clock() < self.startup_deadline

    def _startup_reply_expired(self, decision, meta, captured):
        if not self._startup_retry() or not isinstance(decision, dict):
            return False
        identity = ("protocol_version", "run_id", "frame_id", "sequence", "config_revision")
        if any(decision.get(key) != meta[key] for key in identity):
            return False
        if any(type(decision.get(key)) is not int for key in ("protocol_version", "sequence", "config_revision")):
            return False
        if type(decision.get("valid_for_ms")) is not int or not 0 <= decision["valid_for_ms"] <= 200:
            return False
        if decision.get("state") not in {"clear", "unknown"}:
            return False
        remaining = self.policy["decision_budget_ms"] / 1000 - (self.clock() - captured)
        valid = decision.get("valid_for_ms")
        return remaining < 0.05 or type(valid) is int and valid < 50

    def _retry_observation(self, exc):
        if self.policy["mode"] != "observe" and not self._startup_retry():
            return False
        if isinstance(exc, urllib.error.HTTPError):
            if exc.code == 409:
                try:
                    detail = json.loads(exc.read(4097)).get("detail", {})
                    return isinstance(detail, dict) and detail.get("code") == "stream_frame_unavailable"
                except (ValueError, TypeError, AttributeError):
                    return False
            return exc.code in {408, 429, 500, 502, 503, 504}
        return isinstance(exc, (TimeoutError, socket.timeout, urllib.error.URLError, ConnectionError))

    def _status(self, decision):
        import os
        from pathlib import Path

        from services.compute_config import _write

        target = Path(os.getenv("RIDER_NAVIGATION_STATUS", "/run/rider-motion/navigation_loop.json"))
        row = {
            "observed_at": time.time(),
            "mode": self.policy["mode"],
            "run_id": self.run_id,
            "generation": self.generation,
            "operator_request_id": (self.intent or {}).get("request_id"),
            "config_revision": self.policy["revision"],
            "decision": decision,
            "request_roundtrip_ms": self.request_roundtrip_ms,
            "response_age_ms": self.response_age_ms,
            "latched": self.lease.latched,
            "paused": self.policy["mode"] == "drive"
            and not self.lease.latched
            and not self.lease.moving
            and (self.lease.deadline is not None or self.lease.feedback_deadline is not None),
            "feedback_remaining_ms": max(0, round((self.lease.feedback_deadline - self.clock()) * 1000, 2))
            if self.lease.feedback_deadline is not None
            else 0,
            "permit_remaining_ms": max(0, round((self.lease.deadline - self.clock()) * 1000, 2))
            if self.lease.deadline is not None
            else 0,
            "sampled_monotonic": self.clock(),
            "run_started_monotonic": self.run_started_monotonic,
            "cycle_timings_ms": dict(self.cycle_timings_ms),
            "cycle_elapsed_ms": round((self.clock() - self.cycle_started) * 1000, 2),
            "previous_status_write_ms": self.previous_status_write_ms,
            "visual_pause_supported": True,
            "running": not self.closed.is_set(),
            "stop_reason": self.lease.reason,
            "motion_failure": self.motion_failure,
        }
        status_started = self.clock()
        try:
            _write(target, row)
        finally:
            # This row is already serialized; report its cost in the next sample.
            self.previous_status_write_ms = round((self.clock() - status_started) * 1000, 2)
        if self.policy["mode"] == "drive":
            self.decision_trace.append(dict(row))
            if self.closed.is_set():
                # Persist only after the drive has stopped; observation never
                # replaces its outcome or writes to the drive recorder.
                archive = io.BytesIO()
                with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
                    frames = []
                    for index, frame in enumerate(self.frame_trace):
                        name = f"frame-{index}.jpg"
                        bundle.writestr(zipfile.ZipInfo(name), frame["data"])
                        frames.append(
                            {
                                "file": name,
                                "captured_at": frame["captured_at"],
                                "input_id": frame["input_id"],
                                "sha256": hashlib.sha256(frame["data"]).hexdigest(),
                            }
                        )
                    bundle.writestr(
                        zipfile.ZipInfo("manifest.json"),
                        json.dumps(
                            {
                                "outcome": row,
                                "decisions": list(self.decision_trace),
                                "frames": frames,
                            }
                        ),
                    )
                temporary = target.with_name(".navigation-trial-" + self.run_id + ".tmp")
                try:
                    temporary.write_bytes(archive.getvalue())
                    temporary.replace(target.with_name("navigation_trial.zip"))
                    _write(target.with_name("navigation_trial.json"), row)
                finally:
                    temporary.unlink(missing_ok=True)

    def watch(self):
        while not self.closed.wait(0.02):
            try:
                if not self.lease.tick():
                    self.closed.set()
            except Exception:
                self.closed.set()

    def run(self):
        watchdog = threading.Thread(target=self.watch, daemon=True)
        source = None
        try:
            from apps.compute.stream_prepare import prepare_stream

            prepared = prepare_stream(selection=self.selection)
            source = (
                self.source_factory(
                    require_bytes=False,
                    initial_source=(prepared or {}).get("latest_source"),
                    max_age_ms=self.policy["decision_budget_ms"],
                )
                if self.source_factory is FrameSource
                else self.source_factory()
            )
            if self.policy["mode"] == "drive":
                self.motion_publisher = self.publisher_factory()
            self.run_started_monotonic = self.clock()
            self.started = self.run_started_monotonic
            self.startup_deadline = self.started + 5.0
            if self.policy["mode"] == "drive":
                self._timed("authority_ms", self._authority)
            self._status(None)
            watchdog.start()
            while not self.closed.is_set():
                self.cycle_started = self.clock()
                self.cycle_timings_ms = {}
                configuration_started = self.clock()
                if navigation_config.snapshot() != self.saved_policy or selected_executor() != self.selection:
                    raise ComputeError("navigation_configuration_changed")
                self.cycle_timings_ms["configuration_ms"] = round((self.clock() - configuration_started) * 1000, 2)
                # Recheck authority immediately before every zero/nonzero submission.
                # A second preflight here only delays the next capture and decision.
                frame = self._timed("frame_wait_ms", source.recv, 50)
                if not frame or (self.last_frame is not None and frame["captured_at"] <= self.last_frame[1]):
                    limit = (
                        5.0
                        if not self.fresh_frame_seen or self.policy["mode"] == "observe"
                        else self.policy["decision_budget_ms"] / 1000
                    )
                    if self.clock() - self.started > limit:
                        raise ComputeError("navigation_camera_unavailable")
                    continue
                self.last_frame = (frame["input_id"], frame["captured_at"])
                if (
                    self.policy["mode"] == "drive"
                    and isinstance(frame["data"], bytes)
                    and len(frame["data"]) <= 512 * 1024
                ):
                    self.frame_trace.append(frame)
                source_mono = frame.get("captured_monotonic_ns")
                age = (
                    (self.clock() - source_mono / 1_000_000_000) * 1000
                    if type(source_mono) is int
                    else (time.time() - frame["captured_at"]) * 1000
                )
                if not 0 <= age < self.policy["decision_budget_ms"]:
                    if (
                        self.policy["mode"] == "observe" or self._startup_retry() or not self.fresh_frame_seen
                    ) and self.clock() - self.started <= 5.0:
                        continue
                    raise ComputeError("navigation_frame_expired")
                self.fresh_frame_seen = True
                self.started = self.clock()
                captured = self.clock() - age / 1000
                self.sequence += 1
                frame_id = hashlib.sha256(str(self.last_frame).encode()).hexdigest()
                meta = {
                    "protocol_version": 1,
                    "run_id": self.run_id,
                    "frame_id": frame_id,
                    "sequence": self.sequence,
                    "config_revision": self.policy["revision"],
                    "age_ms": float(age),
                    "deadline_ms": self.policy["decision_budget_ms"],
                    **{k: self.policy[k] for k in ("mode", "corridor", "verified", "calibration_id", "model_sha256")},
                }
                meta["perception"] = self.policy["perception"]
                if self.policy.get("avoidance", {}).get("enabled"):
                    meta.update(
                        protocol_version=self.policy["avoidance"].get("protocol_version", 2),
                        avoidance=self.policy["avoidance"],
                        motion_phase=(
                            "steer_wait"
                            if self.policy["avoidance"].get("protocol_version", 2) == 3
                            else "turn_settling"
                        )
                        if self.turn_capture_after is not None and captured <= self.turn_capture_after
                        else "ready",
                    )
                request_started = self.clock()
                try:
                    decision = self.request(meta, frame["data"], frame["content_type"])
                except (TimeoutError, socket.timeout, urllib.error.URLError, ConnectionError) as exc:
                    if not self._retry_observation(exc):
                        raise
                    self.last_result = {
                        "state": "unknown",
                        "action": "stop",
                        "vision_action": "stop",
                        "reason": "vision_observation_transport_retry",
                        "motion_reason": "vision_observation_transport_retry",
                        "clear_count": 0,
                        "valid_for_ms": 0,
                        **{
                            k: meta[k]
                            for k in ("protocol_version", "run_id", "frame_id", "sequence", "config_revision")
                        },
                    }
                    self.request_roundtrip_ms = round((self.clock() - request_started) * 1000, 2)
                    self.response_age_ms = round((self.clock() - captured) * 1000, 2)
                    self._status(self.last_result)
                    self.closed.wait(0.2)
                    continue
                self.request_roundtrip_ms = round((self.clock() - request_started) * 1000, 2)
                self.response_age_ms = round((self.clock() - captured) * 1000, 2)
                self.last_result = decision
                if self.policy["mode"] == "drive":
                    if self._startup_reply_expired(decision, meta, captured):
                        self.last_result = {
                            **decision,
                            "state": "unknown",
                            "action": "stop",
                            "vision_action": "stop",
                            "reason": "navigation_startup_waiting_fresh_frame",
                            "motion_reason": "navigation_startup_waiting_fresh_frame",
                            "valid_for_ms": 0,
                        }
                        self._status(self.last_result)
                        continue
                    if (
                        self.turn_capture_after is not None
                        and captured <= self.turn_capture_after
                        and decision.get("action") != "stop"
                    ):
                        # A stale orientation can never issue forward or a second turn.
                        decision = {
                            **decision,
                            "action": "stop",
                            "state": "clear",
                            "motion_reason": "avoidance_turn_settling",
                        }
                        self.last_result = decision
                    self._timed("decision_apply_ms", self.lease.accept, decision, frame_id, self.sequence, captured)
                    if not self.lease.latched and self.lease.reason == "awaiting_fresh_decision":
                        # Keep the image verdict, but report the actual ZERO sent
                        # to Pi while waiting for a usable fresh motion permit.
                        decision = {**decision, "action": "stop", "motion_reason": self.lease.reason}
                        self.last_result = decision
                self._status(decision)
                if self.lease.latched:
                    self.closed.set()
                if self.policy["mode"] == "observe":
                    self.closed.wait(0.01)
            return 0
        except Exception as exc:
            if isinstance(exc, ComputeError) and exc.code == "navigation_trial_completed":
                self.closed.set()
                self.motion_failure = None
                with self.lease.lock:
                    self.lease.reason = "trial_completed"
                self.lease.halt("trial_completed")
                return 0
            logging.getLogger(__name__).warning(
                "[vision] navigation failed type=%s reason_type=%s code=%s",
                type(exc).__name__,
                type(getattr(exc, "reason", None)).__name__,
                getattr(exc, "code", None),
            )
            self.lease.halt(exc.code if isinstance(exc, ComputeError) else "navigation_transport_or_input_failed")
            return 2
        finally:
            self.closed.set()
            self.lease.halt("navigation_stopped")
            try:
                self._status(self.last_result)
            except OSError:
                pass
            if source:
                source.close()
            if watchdog.is_alive():
                watchdog.join(1)
            if self.motion_publisher is not None:
                self.motion_publisher.close()
                self.motion_publisher = None
            if self.intent:
                write_intent_status(
                    UNIT,
                    self.intent,
                    active=False,
                    data_ready=False,
                    navigation_ready=False,
                    data_error=self.lease.reason,
                )


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observe", action="store_true")
    runner = NavigationRunner(observe_only=parser.parse_args().observe)
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: runner.closed.set())
    return runner.run()


if __name__ == "__main__":
    raise SystemExit(main())
