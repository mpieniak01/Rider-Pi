"""HTTP evidence precedence is tested without sending a command or starting a service."""

from __future__ import annotations

import pytest
from flask import Flask, request

from services.api_core.operation_result import result_for


@pytest.mark.parametrize(
    "rule,code,body,expected",
    [
        ("/api/control", 200, {"ok": True}, ("unknown", False, None)),
        ("/api/control", 400, {"ok": True}, ("rejected", False, None)),
        ("/api/control", 202, {"ok": True}, ("pending", False, None)),
        ("/api/control", 200, {"ok": True, "state": "partial", "ack": {}, "confirmed": True}, ("partial", False, None)),
        ("/api/control", 200, {"ok": True, "ack": {}, "confirmed": False}, ("unknown", False, "command_accepted")),
        (
            "/api/control",
            200,
            {"ok": True, "ack": {"actuation": True}, "confirmed": True},
            ("executed", True, "sdk_accepted"),
        ),
        ("/api/compute/config", 200, {"persisted": True}, ("executed", True, "configuration_persisted")),
        ("/api/compute/config", 200, {"persisted": True, "ok": False}, ("rejected", False, None)),
        ("/api/compute/config", 200, {"persisted": True, "error": "failure"}, ("unknown", False, None)),
        ("/api/compute/tasks/<task>", 200, {"state": "succeeded"}, ("executed", True, "computation_completed")),
        ("/api/compute/tasks/<task>", 202, {"state": "succeeded"}, ("pending", False, None)),
        ("/api/control", 200, {"ok": True, "task": {"state": "starting"}}, ("pending", False, "task_accepted")),
        (
            "/api/control",
            200,
            {"ok": True, "task": {"state": "running", "ready": True}},
            ("executed", True, "task_ready"),
        ),
        ("/api/control", 200, {"ok": True, "task": {"state": "partial"}}, ("partial", False, None)),
        ("/api/resource/<name>", 200, {"ok": True, "released": True}, ("executed", True, "resource_observed")),
        (
            "/api/resource/<name>",
            200,
            {"ok": True, "confirmation": "control_write_accepted"},
            ("executed", True, "control_write_accepted"),
        ),
        ("/api/control", 200, {"ok": True, "confirmation": "control_write_accepted"}, ("unknown", False, None)),
        ("/api/voice/tts", 200, {"ok": True}, ("executed", True, "application_result")),
        ("/api/chat/send", 200, {"ok": True}, ("executed", True, "application_result")),
        ("/api/voice/tts", 400, {"ok": True}, ("rejected", False, None)),
        (
            "/api/control",
            200,
            {"ok": False, "result": {"ok": True, "ack": {}, "confirmed": True}},
            ("unknown", False, "command_accepted"),
        ),
    ],
)
def test_evidence_keeps_domain_and_terminal_priority(rule, code, body, expected):
    """HTTP success, accepted work and confirmed execution must stay distinct."""
    app = Flask(__name__)
    with app.test_request_context(method="POST"):
        request.view_args = {"name": "lcd"}
        result = result_for(rule, body, code, {"action": "on", "request_id": "request"})
    actual = result["status"], result["confirmed"], result["ack_kind"]
    assert actual == expected


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_reads_never_invent_operation_evidence(method):
    """Mutation evidence is absent from read-only requests, even with a successful body."""
    app = Flask(__name__)
    with app.test_request_context(method=method):
        assert result_for("/api/control", {"ok": True}, 200, {}) is None


def test_nested_identity_and_physical_uncertainty_are_preserved():
    """Domain evidence supplies identity while control-write acknowledgement stays unverified."""
    app = Flask(__name__)
    body = {
        "ok": True,
        "request_id": "outer",
        "result": {
            "request_id": "inner",
            "feature": "feature",
            "confirmation": "control_write_accepted",
        },
    }
    with app.test_request_context(method="PATCH"):
        result = result_for("/api/resource/<name>", body, 200, {"request_id": "command"})
    assert result["request_id"] == "inner"
    assert result["target"] == "feature"
    assert result["action"] == "set"
    assert result["physical_completion"] == "unverified"
