"""Fresh local evidence for an explicitly requested warm navigation epoch."""

from __future__ import annotations

import math
from collections import deque


class Qualification:
    """Count unique fresh clear frames locally; cached pre-resume GO is insufficient."""

    def __init__(self, policy, run_id, started, *, validate_evidence=None):
        self.policy, self.run_id, self.started = policy, run_id, started
        self.validate_evidence = validate_evidence
        self.count = 0
        self.last_sequence = -1
        self.frames = deque(maxlen=3)
        self.source = None

    @staticmethod
    def source_context(decision):
        source = decision.get("source") if isinstance(decision, dict) else None
        return (
            tuple(
                (key, source.get(key))
                for key in ("device_id", "camera_session", "transport_epoch", "pipeline_revision")
            )
            if isinstance(source, dict)
            else None
        )

    def accept(self, decision, frame_id, sequence, captured, now):
        identity = {
            "run_id": self.run_id,
            "frame_id": frame_id,
            "sequence": sequence,
            "config_revision": self.policy["revision"],
        }
        context = self.source_context(decision)
        protocol = (
            self.policy.get("avoidance", {}).get("protocol_version", 2)
            if self.policy.get("avoidance", {}).get("enabled")
            else 1
        )
        valid = (
            isinstance(decision, dict)
            and all(decision.get(key) == value for key, value in identity.items())
            and type(decision.get("config_revision")) is int
            and type(decision.get("protocol_version")) is int
            and decision["protocol_version"] == protocol
            and type(sequence) is int
            and sequence > self.last_sequence
            and frame_id not in self.frames
            and type(captured) in (int, float)
            and math.isfinite(captured)
            and self.started <= captured <= now
            and (now - captured) * 1000 < self.policy["decision_budget_ms"]
            and decision.get("state") == "clear"
            and decision.get("action") in {"go", "stop"}
            and decision.get("model_sha256") == self.policy["model_sha256"]
            and type(decision.get("valid_for_ms")) is int
            and 0 < decision["valid_for_ms"] <= 200
            and (self.validate_evidence is None or self.validate_evidence(decision))
        )
        if not valid:
            self.count = 0
            return False
        if self.count and context != self.source:
            self.count = 0
        self.source = context
        self.frames.append(frame_id)
        self.last_sequence = sequence
        self.count = min(3, self.count + 1)
        return self.count == 3
