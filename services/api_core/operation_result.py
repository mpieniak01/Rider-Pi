"""Bounded HTTP operation projection; an ACK is never invented from HTTP 200."""

from __future__ import annotations

from flask import request

from .contract_registry import contract_for


def result_for(rule, body, code, submitted):
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    command = submitted if isinstance(submitted, dict) else {}
    result = body.get("result") if isinstance(body.get("result"), dict) else body
    ack = result.get("ack") if isinstance(result.get("ack"), dict) else None
    task = result.get("task") if isinstance(result.get("task"), dict) else None
    success = code < 400 and body.get("ok", result.get("ok")) is True
    pending = (
        code == 202
        or result.get("pending") is True
        or task is not None
        and task.get("state") in {"starting", "stopping", "requested"}
    )
    state = (
        "rejected" if code >= 400 else "pending" if pending else "rejected" if result.get("ok") is False else "unknown"
    )
    ack_kind = None
    confirmed = False
    if result.get("state") == "partial" or task is not None and task.get("state") == "partial":
        state = "partial"
    elif ack is not None:
        confirmed = success and result.get("confirmed") is True
        state = "executed" if confirmed else state
        ack_kind = "sdk_accepted" if ack.get("actuation") is True else "command_accepted"
    elif success and result.get("persisted") is True:
        state, confirmed, ack_kind = "executed", True, "configuration_persisted"
    elif success and task is not None:
        ack_kind = "task_ready" if task.get("ready") is True else "task_accepted"
        confirmed = not pending
        state = "pending" if pending else "executed"
    elif success and isinstance(result.get("status"), dict) and result["status"].get("stale") is not True:
        observed = result["status"]
        action = command.get("action")
        if rule == "/api/resource/<name>" and (request.view_args or {}).get("name") == "lcd":
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
        state, ack_kind = ("executed" if confirmed else "pending"), "systemd_observed"
    elif (
        success
        and rule == "/api/resource/<name>"
        and (request.view_args or {}).get("name") == "lcd"
        and command.get("action") == "on"
        and result.get("idempotent") is True
        and isinstance(result.get("face"), dict)
        and result["face"].get("running") is True
        and result["face"].get("sink") == "lcd"
    ):
        state, confirmed, ack_kind = "executed", True, "application_state_observed"
    elif success and result.get("released") is True:
        state, confirmed, ack_kind = "executed", True, "resource_observed"
    elif (
        success
        and contract_for(rule).name == "rider.resources"
        and result.get("confirmation") == "control_write_accepted"
    ):
        state, confirmed, ack_kind = "executed", True, "control_write_accepted"
    elif success and contract_for(rule).name in {"rider.face", "rider.chat", "rider.voice", "rider.home"}:
        state, confirmed, ack_kind = "executed", True, "application_result"
    domain_target = {
        "rider.safety": "motion-executor",
        "rider.calibration": "calibration",
        "rider.odometry": "odometry",
        "rider.navigation": "navigator",
    }.get(contract_for(rule).name)
    return {
        "request_id": result.get("request_id", body.get("request_id", command.get("request_id"))),
        "action": (ack or {}).get("action")
        or result.get("action", command.get("action", "set" if request.method in {"PATCH", "PUT"} else None)),
        "target": result.get("feature", body.get("feature", result.get("unit", body.get("domain"))))
        or next(iter((request.view_args or {}).values()), None)
        or domain_target,
        "status": state,
        "confirmed": confirmed,
        "ack_kind": ack_kind,
        "ack": ack,
        "actuation": ack.get("actuation") is True if ack else result.get("actuation") is True,
        "physical_completion": (ack or result).get(
            "physical_completion", "unverified" if ack_kind == "control_write_accepted" else "not_applicable"
        ),
    }
