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
from apps.compute.navigation_cycle import NavigationCycle
from apps.compute.navigation_transport import NavigationHTTPTransport
from apps.compute.operator_lifecycle import OperatorLifecycle
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


class NavigationRunner(NavigationCycle):
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
        self.decision_transport = None
        self.clock = clock
        self.startup_deadline = clock() + 5.0
        self.closed = threading.Event()
        self.saved_policy = navigation_config.snapshot()
        self.policy = {**self.saved_policy, "mode": "observe"} if observe_only else self.saved_policy
        self.last_result = None
        self.decision_trace = deque(maxlen=12)
        self.frame_trace = deque(maxlen=4)
        self.motion_failure = None
        self.input_failure = None
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
        self.last_source = None
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
        self.operator_lifecycle = OperatorLifecycle(self)

    def _timed(self, phase, callback, *args, **kwargs):
        started = self.clock()
        try:
            return callback(*args, **kwargs)
        finally:
            self.cycle_timings_ms[phase] = round((self.clock() - started) * 1000, 2)

    def _check_navigation_intent(self, safety, intent):
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
        return revision, digest

    def _check_executor_support(self, safety):
        if (
            safety.get("remote_decision_deadline_supported") is not True
            or safety.get("remote_decision_feedback_supported") is not True
            or safety.get("scoped_stop_generation_supported") is not True
        ):
            raise ComputeError("navigation_executor_update_required")
        if self._consent_completed(safety):
            raise ComputeError("navigation_trial_completed")

    def _check_rejected_acks(self, safety):
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

    def _check_pending_acks(self, safety):
        acknowledgements = [safety.get("last_ack") or {}, *(safety.get("recent_acks") or [])]
        for request_id, deadline in self.pending_motion_acks.copy().items():
            ack = next((row for row in acknowledgements if row.get("request_id") == request_id), None)
            if ack and ack.get("status") == "executed" and ack.get("accepted") is True:
                del self.pending_motion_acks[request_id]
            elif self.clock() >= deadline:
                self.motion_failure = {"http_status": 504, "reason": "navigation_motion_ack_timeout"}
                raise ComputeError("navigation_motion_ack_timeout")

    def _live_intent(self, safety):
        return self._timed("intent_read_ms", read_service_intent, UNIT, safety.get("generation"))

    def _authority(self):
        safety = self._timed("safety_read_ms", read_status)
        if self.operator_lifecycle.enabled:
            return self.operator_lifecycle.sync(safety)
        if self.policy["mode"] == "observe":
            return False
        self._check_executor_support(safety)
        self._check_rejected_acks(safety)
        self._check_pending_acks(safety)
        intent = self._live_intent(safety)
        revision, digest = self._check_navigation_intent(safety, intent)
        self.settings_revision, self.calibration_digest = revision, digest
        self.intent = intent
        self.operator_lifecycle.admit(safety, intent)
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

    def drive(self, speed, duration, *, yaw=0.0, expected_run_id=None):
        if not self._timed("authority_ms", self._authority):
            raise ComputeError("navigation_authority_lost")
        generation = self.generation
        operation = self.operator_lifecycle.operation
        if expected_run_id is not None and self.run_id != expected_run_id:
            raise ComputeError("navigation_operation_stale")
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
                "generation": generation,
                "seq": self.motion_sequence,
                "request_id": self.run_id + "-" + str(self.motion_sequence),
                "ts": time.time(),
                "ttl_ms": 100,
                "settings_revision": self.settings_revision,
                **({"operator_operation_id": operation} if self.operator_lifecycle.enabled else {}),
                **(
                    {"journey_version": 1, "journey_id": self.lease.journey.context["id"]}
                    if self.lease.journey is not None
                    else {}
                ),
                "decision_deadline_monotonic": self.lease.deadline,
                "decision_feedback_deadline_monotonic": self.lease.feedback_deadline,
                "vx": speed,
                "yaw": yaw,
                "duration": duration,
            },
            **({"publisher": self.motion_publisher, "timeout_s": 0.0} if self.motion_publisher is not None else {}),
        )
        if not self._record_motion_submission(speed, yaw, result, code):
            self._motion_rejected(result, code)

    def _record_motion_submission(self, speed, yaw, result, code):
        accepted = (code == 200 and result.get("ok")) or (code == 202 and result.get("pending"))
        if accepted:
            self.motion_started = self.motion_started or speed != 0 or yaw != 0
        if code == 202 and result.get("pending"):
            self.pending_motion_acks[self.run_id + "-" + str(self.motion_sequence)] = self.clock() + 0.1
        return accepted

    def _motion_rejected(self, result, code):
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

    def turn(self, side, duration, *, expected_run_id=None):
        settings = self.policy["avoidance"]
        if side not in {"left", "right"} or not settings["enabled"] or not settings["sweep_verified"]:
            raise ComputeError("navigation_avoidance_not_accepted")
        self.drive(
            0.0, duration, yaw=settings["turn_speed"] * (1 if side == "left" else -1), expected_run_id=expected_run_id
        )
        # Actuation cannot outlive the Pi-local permit. Require a capture after
        # that bound and settling, not merely a reply received after the turn.
        self.turn_capture_after = self.lease.deadline + 0.1

    def steer(self, side, duration, *, expected_run_id=None):
        settings = self.policy["avoidance"]
        if (
            side not in {"left", "right"}
            or not settings["enabled"]
            or not settings["sweep_verified"]
            or settings["protocol_version"] != 3
        ):
            raise ComputeError("navigation_avoidance_not_accepted")
        self.drive(
            self.policy["speed"],
            duration,
            yaw=settings["turn_speed"] * (1 if side == "left" else -1),
            expected_run_id=expected_run_id,
        )
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

    def pause(self, duration, *, expected_run_id=None):
        self.drive(0.0, duration, expected_run_id=expected_run_id)

    def stop(self, *, expected_run_id=None, expected_generation=None):
        if expected_run_id is not None and expected_run_id != self.run_id:
            return
        generation = self.generation if expected_generation is None else expected_generation
        run_id = self.run_id if expected_run_id is None else expected_run_id
        if self.policy["mode"] != "drive":
            return
        safety = read_status()
        if safety.get("owner") != "navigation" or safety.get("generation") != generation:
            return
        _, code = submit_control(
            {
                "action": "stop",
                "source": "navigation",
                "owner": "navigation",
                "request_id": run_id + "-stop",
                "expected_generation": generation,
                **({"reason": self.lease.reason} if self.operator_lifecycle.enabled else {}),
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
        if self.decision_transport is None:
            self.decision_transport = NavigationHTTPTransport(self.selection["url"], clock=self.clock)
        with self.decision_transport.open(req, timeout=timeout) as response:
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
        if self.operator_lifecycle.enabled and self.policy["mode"] == "drive":
            self.lease.halt("navigation_transport_or_input_failed")
            self._authority()
        if self.policy["mode"] != "observe" and not self._startup_retry():
            return False
        if isinstance(exc, urllib.error.HTTPError):
            if exc.code == 409:
                from apps.compute.stream_prepare import http_error_code

                code = http_error_code(exc)
                return code == "stream_frame_unavailable" or (
                    self.policy["mode"] == "observe" and code == "vision_frame_expired"
                )
            return exc.code in {408, 429, 500, 502, 503, 504}
        return isinstance(exc, (TimeoutError, socket.timeout, urllib.error.URLError, ConnectionError))

    def _status(self, decision, *, terminal=False):
        import os
        from pathlib import Path

        from services.compute_config import _write

        target = Path(os.getenv("RIDER_NAVIGATION_STATUS", "/run/rider-motion/navigation_loop.json"))
        row = {
            "observed_at": time.time(),
            **self.operator_lifecycle.status(),
            "mode": self.policy["mode"],
            "run_id": self.run_id,
            "generation": self.generation,
            "operator_request_id": (self.intent or {}).get("request_id"),
            "config_revision": self.policy["revision"],
            "decision": decision,
            "request_roundtrip_ms": self.request_roundtrip_ms,
            "decision_transport": self.decision_transport.status()
            if callable(getattr(self.decision_transport, "status", None))
            else None,
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
            "running": not self.closed.is_set() and not terminal,
            "stop_reason": self.lease.reason,
            "motion_failure": self.motion_failure,
            "input_failure": self.input_failure,
        }
        status_started = self.clock()
        try:
            _write(target, row)
        finally:
            # This row is already serialized; report its cost in the next sample.
            self.previous_status_write_ms = round((self.clock() - status_started) * 1000, 2)
        if self.policy["mode"] == "drive":
            self.decision_trace.append(dict(row))
            if self.closed.is_set() or terminal:
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
                    if self.operator_lifecycle.enabled:
                        self._authority()
                    else:
                        self.closed.set()
            except Exception:
                self.closed.set()

    def _start_cycle(self):
        self.cycle_started = self.clock()
        self.cycle_timings_ms = {}
        configuration_started = self.clock()
        if navigation_config.snapshot() != self.saved_policy or selected_executor() != self.selection:
            raise ComputeError("navigation_configuration_changed")
        self.cycle_timings_ms["configuration_ms"] = round((self.clock() - configuration_started) * 1000, 2)
        if self.operator_lifecycle.enabled:
            self._timed("authority_ms", self._authority)
            if self.operator_lifecycle.authorized and not self.motion_started and self.clock() >= self.startup_deadline:
                self.lease.halt("navigation_qualification_timeout")
                self._authority()
        # Recheck authority immediately before every zero/nonzero submission.
        # A second preflight here only delays the next capture and decision.

    def _start_run(self):
        from apps.compute.stream_prepare import prepare_stream

        prepared = prepare_stream(selection=self.selection, max_age_ms=self.policy["decision_budget_ms"])
        source = (
            self.source_factory(
                require_bytes=False,
                initial_source=(prepared or {}).get("latest_source"),
                max_age_ms=self.policy["decision_budget_ms"],
            )
            if self.source_factory is FrameSource
            else self.source_factory()
        )
        return source

    def _start_watch(self):
        if self.policy["mode"] == "drive":
            self.motion_publisher = self.publisher_factory()
        self.run_started_monotonic = self.clock()
        self.started = self.run_started_monotonic
        self.startup_deadline = self.started + 5.0
        if self.policy["mode"] == "drive":
            self._timed("authority_ms", self._authority)
        self._status(None)

    def _run_failure(self, exc):
        if isinstance(exc, ComputeError) and exc.code == "navigation_trial_completed":
            self.closed.set()
            self.motion_failure = None
            with self.lease.lock:
                self.lease.reason = "trial_completed"
            self.lease.halt("trial_completed")
            return 0
        failure = exc
        if isinstance(exc, urllib.error.HTTPError):
            from apps.compute.stream_prepare import http_error_code

            failure = ComputeError("navigation_" + http_error_code(exc), exc.code)
        self.input_failure = {
            "error_type": type(exc).__name__,
            "reason_type": type(getattr(exc, "reason", None)).__name__,
            "code": failure.code if isinstance(failure, ComputeError) else "navigation_transport_or_input_failed",
            "http_status": getattr(failure, "status", None),
        }
        logging.getLogger(__name__).warning(
            "[vision] navigation failed type=%s reason_type=%s code=%s http_status=%s",
            type(exc).__name__,
            type(getattr(exc, "reason", None)).__name__,
            getattr(failure, "code", None),
            getattr(failure, "status", None),
        )
        self.lease.halt(failure.code if isinstance(failure, ComputeError) else "navigation_transport_or_input_failed")
        return 2

    def _finish_run(self, source, watchdog):
        self.closed.set()
        self.lease.halt("navigation_stopped")
        try:
            self._status(self.last_result)
        except OSError:
            pass
        if self.decision_transport is not None:
            self.decision_transport.close()
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

    def run(self):
        watchdog = threading.Thread(target=self.watch, daemon=True)
        source = None
        try:
            source = self._start_run()
            self._start_watch()
            watchdog.start()
            while not self.closed.is_set():
                try:
                    self._run_cycle(source)
                except Exception as exc:
                    lifecycle = self.operator_lifecycle
                    incompatible = isinstance(exc, ComputeError) and exc.code in {
                        "navigation_configuration_changed",
                        "navigation_journey_source_changed",
                        "navigation_calibration_changed",
                        "navigation_settings_stale",
                    }
                    if lifecycle.journey_id is None or incompatible:
                        raise
                    self._run_failure(exc)
                    # Failure ends this mission, not its passive source/connection.
                    # The old lease is latched; sync can only retire it to observe.
                    self._authority()
                    self._status(self.last_result)

            return 0
        except Exception as exc:
            return self._run_failure(exc)
        finally:
            self._finish_run(source, watchdog)


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
