"""Pi transport and bounded actuation; visual inference runs only on Venom."""

from __future__ import annotations

import json
import signal
import threading
import time
import urllib.request
import uuid

from apps.compute.client import ComputeError
from apps.compute.decision_lease import DecisionLease
from apps.compute.runners import FrameSource, selected_executor
from apps.safety.intent import read_service_intent, write_intent_status
from services import navigation_config
from services.control_commands import submit_control
from services.safety_contract import read_status

UNIT = "rider-venom-navigation.service"


class NavigationRunner:
    def __init__(self, *, source_factory=FrameSource, request=None, clock=time.monotonic):
        self.source_factory = source_factory
        self.request = request or self._request
        self.clock = clock
        self.closed = threading.Event()
        self.policy = navigation_config.snapshot()
        self.selection = selected_executor()
        if not self.selection:
            raise ComputeError("compute_executor_not_selected")
        self.run_id = uuid.uuid4().hex
        self.sequence = 0
        self.motion_sequence = -1
        self.intent = None
        self.generation = None
        self.last_frame = None
        self.lease = DecisionLease(self.policy, self.run_id, self.drive, self.stop, clock)
        self.started = clock()

    def _authority(self):
        safety = read_status()
        if self.policy["mode"] == "observe":
            return False
        intent = read_service_intent(UNIT, safety.get("generation"))
        if (
            safety.get("can_move") is not True
            or safety.get("owner") != "navigation"
            or not intent
            or (self.generation and self.generation != safety.get("generation"))
        ):
            raise ComputeError("navigation_authority_lost")
        if self.intent and self.intent["request_id"] != intent["request_id"]:
            raise ComputeError("navigation_intent_changed")
        self.intent = intent
        self.generation = safety["generation"]
        self.motion_sequence = max(self.motion_sequence, safety.get("last_seq", -1), intent["seq"])
        if not write_intent_status(
            UNIT, intent, active=self.lease.moving, data_ready=self.lease.moving, navigation_ready=self.lease.moving
        ):
            raise ComputeError("navigation_producer_claim_failed")
        return True

    def drive(self, speed, duration):
        self._authority()
        self.motion_sequence += 1
        result, code = submit_control(
            {
                "action": "move",
                "source": "navigation",
                "execution_context": "panel",
                "generation": self.generation,
                "seq": self.motion_sequence,
                "request_id": self.run_id + "-" + str(self.motion_sequence),
                "ts": time.time(),
                "ttl_ms": 100,
                "vx": speed,
                "yaw": 0.0,
                "duration": duration,
            }
        )
        if not (code == 200 and result.get("ok") or code == 202 and result.get("pending")):
            raise ComputeError("navigation_motion_rejected")

    def stop(self):
        if self.policy["mode"] != "drive":
            return
        safety = read_status()
        if safety.get("owner") != "navigation" or safety.get("generation") != self.generation:
            return
        _, code = submit_control(
            {"action": "stop", "source": "navigation", "owner": "navigation", "request_id": self.run_id + "-stop"}
        )
        if code not in {200, 202}:
            self.closed.set()

    def _request(self, meta, payload, mime):
        base = self.selection["url"].rstrip("/")
        if not base.endswith("/api/v1/rider/compute"):
            base += "/api/v1/rider/compute"
        req = urllib.request.Request(
            base + "/vision/decision",
            data=payload,
            headers={
                "Content-Type": mime,
                "X-Rider-Device": self.selection["device_id"],
                "Authorization": "Bearer " + self.selection["token"],
                "X-Rider-Vision": json.dumps(meta),
            },
        )
        with urllib.request.urlopen(req, timeout=self.policy["decision_budget_ms"] / 1000) as response:
            body = response.read(16385)
            if len(body) > 16384:
                raise ComputeError("navigation_response_bounds")
            return json.loads(body)

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
            source = self.source_factory()
            watchdog.start()
            while not self.closed.is_set():
                if navigation_config.snapshot() != self.policy or selected_executor() != self.selection:
                    raise ComputeError("navigation_configuration_changed")
                if self.policy["mode"] == "drive":
                    self._authority()
                frame = source.recv(50)
                if not frame or (frame["input_id"], frame["captured_at"]) == self.last_frame:
                    if self.clock() - self.started > self.policy["decision_budget_ms"] / 1000:
                        raise ComputeError("navigation_camera_unavailable")
                    continue
                self.last_frame = (frame["input_id"], frame["captured_at"])
                self.started = self.clock()
                age = (time.time() - frame["captured_at"]) * 1000
                if not 0 <= age < self.policy["decision_budget_ms"]:
                    raise ComputeError("navigation_frame_expired")
                captured = self.clock() - age / 1000
                self.sequence += 1
                meta = {
                    "protocol_version": 1,
                    "run_id": self.run_id,
                    "frame_id": frame["input_id"],
                    "sequence": self.sequence,
                    "config_revision": self.policy["revision"],
                    "age_ms": float(age),
                    "deadline_ms": self.policy["decision_budget_ms"],
                    **{k: self.policy[k] for k in ("mode", "corridor", "verified", "calibration_id", "model_sha256")},
                }
                decision = self.request(meta, frame["data"], frame["content_type"])
                self.lease.accept(decision, frame["input_id"], self.sequence, captured)
                if self.lease.latched:
                    self.closed.set()
                self.closed.wait(0.01)
            return 0
        except Exception:
            self.lease.halt("navigation_transport_or_input_failed")
            return 2
        finally:
            self.closed.set()
            if source:
                source.close()
            self.lease.halt("navigation_stopped")
            if watchdog.is_alive():
                watchdog.join(1)
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
    runner = NavigationRunner()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: runner.closed.set())
    return runner.run()


if __name__ == "__main__":
    raise SystemExit(main())
