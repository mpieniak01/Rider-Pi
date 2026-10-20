"""Pi-owned mission identity and maneuver progress, independent of motor TTL."""

from __future__ import annotations


class JourneyProgress:
    def __init__(self, identity, clock):
        if (
            not isinstance(identity, dict)
            or set(identity) != {"version", "id", "maneuver_epoch"}
            or type(identity.get("version")) is not int
            or identity["version"] != 1
            or not isinstance(identity.get("id"), str)
            or not 1 <= len(identity["id"]) <= 128
            or any(char.isspace() for char in identity["id"])
            or type(identity.get("maneuver_epoch")) is not int
            or identity["maneuver_epoch"] != 0
        ):
            raise ValueError("navigation_journey_invalid")
        self.context = dict(identity)
        self.clock = clock
        self.started = clock()
        self.ended = None
        self.active = True
        self.state = "qualifying"
        self.reason = "awaiting_fresh_qualification"
        self.host_session = None
        self.source_bound = False
        self.source_context = None
        self.capture_bound = False
        self.capture_context = None
        self.after_correction = None
        self.clear_count = 0

    def validate_reply(self, decision):
        if not isinstance(decision, dict):
            return False
        identity = decision.get("journey")
        host = decision.get("host_session")
        source = decision.get("source")
        context = (
            tuple(source.get(key) for key in ("device_id", "camera_session", "transport_epoch", "pipeline_revision"))
            if isinstance(source, dict)
            else None
        )
        valid = (
            isinstance(identity, dict)
            and set(identity) == set(self.context)
            and type(identity.get("version")) is int
            and type(identity.get("maneuver_epoch")) is int
            and identity == self.context
            and isinstance(host, str)
            and 1 <= len(host) <= 128
            and not any(char.isspace() for char in host)
            and (self.host_session is None or host == self.host_session)
            and (not self.source_bound or context == self.source_context)
        )
        if valid and self.host_session is None:
            self.host_session = host
            self.source_context = context
            self.source_bound = True
        return valid

    def validate_capture(self, frame):
        source = frame.get("source")
        context = (
            tuple(source.get(key) for key in ("camera_session", "transport_epoch", "pipeline_revision"))
            if isinstance(source, dict)
            else None
        )
        if self.capture_bound and context != self.capture_context:
            return False
        self.capture_bound = True
        self.capture_context = context
        return True

    def corrected(self, action, deadline):
        self.after_correction = deadline + 0.1
        self.clear_count = 0
        self.state, self.reason = action, "avoidance_correction"

    def clear(self, captured):
        self.state, self.reason = "forward", "fresh_clear_path"
        if self.after_correction is None or captured <= self.after_correction:
            return False
        self.clear_count += 1
        if self.clear_count < 3:
            return False
        self.context["maneuver_epoch"] += 1
        self.after_correction = None
        self.clear_count = 0
        return True

    def waiting(self, reason, *, reset_clear=True):
        if reset_clear:
            self.clear_count = 0
        self.state, self.reason = "waiting", reason

    def end(self, reason):
        if self.active:
            self.active = False
            self.ended = self.clock()
            self.reason = reason
            self.state = (
                "blocked"
                if reason.startswith("avoidance_")
                else "stopped"
                if reason
                in {"operator_stop", "operator_intervention", "navigation_stopped", "navigation_authority_lost"}
                else "failed"
            )

    def snapshot(self):
        return {
            **self.context,
            "active": self.active,
            "state": self.state,
            "reason": self.reason,
            "elapsed_s": round(max(0.0, (self.clock() if self.active else self.ended) - self.started), 3),
        }
