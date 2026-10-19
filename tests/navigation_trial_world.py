"""Temporary orchestration world with a fake clock, service runner and motion gate."""

import copy
import json
import time

import pytest

from apps.safety.gate import MotionGate
from common.service_catalog import DEFAULT_REGISTRY
from services import navigation_config
from services.core.features import FeatureManager, NullPublisher
from services.navigation_trial import NavigationTrial
from services.safety_contract import command_envelope


class World:
    def __init__(self, tmp_path):
        self.gate = MotionGate(blocked=lambda: False)
        self.active, self.actions, self.commands = set(), [], []
        self.hook = None
        self.elapsed = 0.0
        self.failure = None
        self.config_path = tmp_path / "navigation.json"
        policy = copy.deepcopy(navigation_config.DEFAULT)
        policy.update(verified=True, calibration_id="accepted", model_sha256="a" * 64)
        self.config_path.write_text(json.dumps(policy))
        self.manager = FeatureManager(
            registry={
                key: DEFAULT_REGISTRY[key]
                for key in ("s2_camera_preview", "s14_venom_navigation", "s15_venom_perception")
            },
            runner=self.run,
            status_fn=self.unit_status,
            publisher=NullPublisher(),
            safety_status=self.safety,
            safety_stop=lambda _: pytest.fail("A trial must never use global cleanup STOP"),
            dependency_check=lambda *_: [],
            producer_status=lambda _: {},
            state_path=tmp_path / "features.json",
        )
        self.trial = NavigationTrial(
            self.manager,
            safety=self.safety,
            submit=self.submit,
            settings=lambda: {"revision": 3},
            status=self.status,
            clock=lambda: self.elapsed,
            sleep=self.sleep,
        )

    def sleep(self, seconds):
        self.elapsed += seconds

    def safety(self):
        return {
            **self.gate.snapshot(),
            "ready": True,
            "stale": False,
            "can_move": self.gate.can_actuate(),
            "hardware_ready": True,
            "remote_decision_deadline_supported": True,
            "remote_decision_feedback_supported": True,
            "scoped_stop_generation_supported": True,
            "manual_settings": {"revision": 3},
            "capabilities": {name: {"available": True, "stop_verified": True} for name in ("move", "turn")},
        }

    def submit(self, payload):
        self.commands.append(dict(payload))
        command = command_envelope(payload)
        accepted, reason = self.gate.authorize(command)
        return {
            "ok": accepted,
            "confirmed": accepted,
            "error": None if accepted else reason,
            "ack": {"generation": self.gate.generation, "request_id": command["request_id"]},
            "safety": self.safety(),
        }, 200 if accepted else 409

    def unit_status(self, unit):
        return {
            "unit": unit,
            "load": "loaded",
            "active": "active" if unit in self.active else "inactive",
            "sub": "running" if unit in self.active else "dead",
        }

    def run(self, unit, action):
        self.actions.append((unit, action))
        if self.hook:
            self.hook(unit, action)
        if self.failure == (unit, action):
            return {"ok": False, "error": "fixture_start_failure"}
        if action == "start":
            self.active.add(unit)
        else:
            self.active.discard(unit)
        return {"ok": True, "unit": unit, "action": action}

    def status(self):
        intent = self.manager._intents.get("s14_venom_navigation", {})
        if not intent:
            return {}
        return {
            "run_id": "new-run",
            "mode": "drive",
            "running": True,
            "observed_at": time.time(),
            "config_revision": navigation_config.snapshot()["revision"],
            "generation": self.gate.generation,
            "operator_request_id": intent["request_id"],
            "sampled_monotonic": self.elapsed,
            "permit_remaining_ms": 150,
            "response_age_ms": 40,
        }

    def body(self, **changes):
        return {
            "request_id": "operator-click",
            "generation": self.gate.generation,
            "ts": time.time(),
            "ttl_ms": 500,
            "config_revision": navigation_config.snapshot()["revision"],
            "settings_revision": 3,
            "operator_consent": True,
            "operator_plan": "Forward, current low speed, up to 10 seconds.",
            "source": "manual",
            "execution_context": "panel",
            **changes,
        }

    def arm_manual(self):
        return self.submit(
            {
                "action": "arm",
                "source": "manual",
                "owner": "manual",
                "request_id": "new-manual",
                "generation": self.gate.generation,
                "seq": 0,
                "ts": time.time(),
                "ttl_ms": 500,
                "operator_consent": True,
                "operator_plan": "Manual operator takeover",
                "execution_context": "panel",
                "arming_mode": "operator",
            }
        )
