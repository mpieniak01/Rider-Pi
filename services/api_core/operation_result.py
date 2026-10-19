"""Bounded HTTP operation projection; an ACK is never invented from HTTP 200."""

from __future__ import annotations

from flask import request

from .contract_registry import contract_for

_DOMAIN_TARGETS = {
    "rider.safety": "motion-executor",
    "rider.calibration": "calibration",
    "rider.odometry": "odometry",
    "rider.navigation": "navigator",
}


def _initial_state(code, result, pending):
    if code >= 400:
        return "rejected"
    if pending:
        return "pending"
    if result.get("ok") is False:
        return "rejected"
    return "unknown"


class _OperationEvidence:
    """Resolve existing evidence sources in their original precedence order."""

    def __init__(self, rule, body, code, submitted):
        self.rule = rule
        self.body = body
        self.code = code
        self.command = submitted if isinstance(submitted, dict) else {}
        self.result = body.get("result") if isinstance(body.get("result"), dict) else body
        self.ack = self.result.get("ack") if isinstance(self.result.get("ack"), dict) else None
        self.task = self.result.get("task") if isinstance(self.result.get("task"), dict) else None
        self.success = code < 400 and body.get("ok", self.result.get("ok")) is True
        self.pending = (
            code == 202
            or self.result.get("pending") is True
            or self.task is not None
            and self.task.get("state") in {"starting", "stopping", "requested"}
        )
        self.contract = contract_for(rule).name
        self.initial_state = _initial_state(code, self.result, self.pending)

    def _compute_success(self):
        """Compute protocols expose persistence or a terminal job state instead of legacy ok."""
        return (
            self.code < 400
            and not self.pending
            and self.body.get("ok") is not False
            and self.result.get("ok") is not False
            and not self.body.get("error")
            and not self.result.get("error")
            and self.contract == "rider.compute"
        )

    def _domain_projection(self):
        compute_success = self._compute_success()
        if self.result.get("persisted") is True and (
            self.success or compute_success and self.rule == "/api/compute/config"
        ):
            return "executed", True, "configuration_persisted"
        if compute_success and self.rule == "/api/compute/tasks/<task>" and self.result.get("state") == "succeeded":
            return "executed", True, "computation_completed"
        return None

    def _task_projection(self):
        if self.success and self.task is not None:
            kind = "task_ready" if self.task.get("ready") is True else "task_accepted"
            return ("pending" if self.pending else "executed"), not self.pending, kind
        return None

    def _unit_projection(self, observed):
        action = self.command.get("action")
        if self.rule == "/api/resource/<name>" and (request.view_args or {}).get("name") == "lcd":
            action = {"on": "start", "off": "stop"}.get(action, action)
        active = observed.get("active_state", observed.get("active"))
        enabled = observed.get("unit_file_state", observed.get("enabled"))
        confirmed = (
            action in {"start", "restart"}
            and active == "active"
            or action == "stop"
            and active == "inactive"
            or action == "enable"
            and enabled in {"enabled", "enabled-runtime"}
            or action == "disable"
            and enabled == "disabled"
        )
        return ("executed" if confirmed else "pending"), confirmed, "systemd_observed"

    def _lcd_runtime_observed(self):
        return (
            self.success
            and self.rule == "/api/resource/<name>"
            and (request.view_args or {}).get("name") == "lcd"
            and self.command.get("action") == "on"
            and self.result.get("idempotent") is True
            and isinstance(self.result.get("face"), dict)
            and self.result["face"].get("running") is True
            and self.result["face"].get("sink") == "lcd"
        )

    def _resource_projection(self):
        observed = self.result.get("status")
        if self.success and isinstance(observed, dict) and observed.get("stale") is not True:
            return self._unit_projection(observed)
        if self._lcd_runtime_observed():
            return "executed", True, "application_state_observed"
        return None

    def _application_projection(self):
        if not self.success:
            return None
        if self.result.get("released") is True:
            return "executed", True, "resource_observed"
        if self.contract == "rider.resources" and self.result.get("confirmation") == "control_write_accepted":
            return "executed", True, "control_write_accepted"
        if self.contract in {"rider.face", "rider.chat", "rider.voice", "rider.home"}:
            return "executed", True, "application_result"
        return None

    def resolve(self):
        if self.result.get("state") == "partial" or self.task is not None and self.task.get("state") == "partial":
            return "partial", False, None
        if self.ack is not None:
            confirmed = self.success and self.result.get("confirmed") is True
            kind = "sdk_accepted" if self.ack.get("actuation") is True else "command_accepted"
            return ("executed" if confirmed else self.initial_state), confirmed, kind
        for project in (
            self._domain_projection,
            self._task_projection,
            self._resource_projection,
            self._application_projection,
        ):
            evidence = project()
            if evidence is not None:
                return evidence
        return self.initial_state, False, None

    def projection(self):
        state, confirmed, ack_kind = self.resolve()
        result, command, ack = self.result, self.command, self.ack
        return {
            "request_id": result.get("request_id", self.body.get("request_id", command.get("request_id"))),
            "action": (ack or {}).get("action")
            or result.get("action", command.get("action", "set" if request.method in {"PATCH", "PUT"} else None)),
            "target": result.get("feature", self.body.get("feature", result.get("unit", self.body.get("domain"))))
            or next(iter((request.view_args or {}).values()), None)
            or _DOMAIN_TARGETS.get(self.contract),
            "status": state,
            "confirmed": confirmed,
            "ack_kind": ack_kind,
            "ack": ack,
            "actuation": ack.get("actuation") is True if ack else result.get("actuation") is True,
            "physical_completion": (ack or result).get(
                "physical_completion", "unverified" if ack_kind == "control_write_accepted" else "not_applicable"
            ),
        }


def result_for(rule, body, code, submitted):
    """Project only mutation evidence; keep legacy/domain payloads and public imports intact."""
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    return _OperationEvidence(rule, body, code, submitted).projection()
