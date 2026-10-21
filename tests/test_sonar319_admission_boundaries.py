"""Regression boundaries for the Sonar navigation refactor; no robot IO."""

import urllib.request
from types import SimpleNamespace

import pytest

from apps.compute.client import ComputeError
from apps.compute.navigation_transport import NavigationHTTPTransport
from apps.safety.operator_control import OperatorControl


@pytest.mark.parametrize(
    "url,method",
    [
        ("http://127.0.0.1/api/v1/rider/compute/vision/decision?redirect=yes", "POST"),
        ("http://127.0.0.1/api/v1/rider/compute/vision/decision#fragment", "POST"),
        ("http://fixture@127.0.0.1/api/v1/rider/compute/vision/decision", "POST"),
        ("http://fixture:unused@127.0.0.1/api/v1/rider/compute/vision/decision", "POST"),
        ("http://127.0.0.1/api/control", "POST"),
        ("http://127.0.0.1/api/v1/rider/compute/vision/decision", "GET"),
    ],
)
def test_invalid_target_is_rejected_before_connection_creation(url, method):
    transport = NavigationHTTPTransport("http://127.0.0.1")
    request = urllib.request.Request(url, data=b"fixture", method=method)
    with pytest.raises(ComputeError, match="navigation_transport_target_invalid"):
        transport.open(request, timeout=0.1)
    assert transport.connection is None
    assert transport.status() == {"connections": 0, "requests": 0}
    transport.close()


def test_closed_transport_precedes_target_validation():
    transport = NavigationHTTPTransport("http://127.0.0.1")
    transport.close()
    request = urllib.request.Request("http://different-origin.invalid/api/control", data=b"fixture")
    with pytest.raises(ComputeError, match="navigation_transport_closed"):
        transport.open(request, timeout=0.1)
    assert transport.requests == 0


def test_transfer_rejection_order_and_journey_resume_do_not_extend_consent():
    gate = SimpleNamespace(
        can_actuate=lambda: False,
        state="ESTOP",
        panel_id="panel",
        owner="navigation",
        arming_mode="journey",
        lease_deadline=3.0,
        clock=lambda: 1.0,
    )
    control = OperatorControl(gate)
    command = {"action": "navigation_resume", "source": "agent", "execution_context": "chat", "panel_id": "other"}
    with pytest.raises(ValueError, match="operator_control_not_available"):
        control._validate_transfer(command)
    control.enabled = True
    with pytest.raises(ValueError, match="estop_latched"):
        control._validate_transfer(command)
    gate.can_actuate = lambda: True
    with pytest.raises(ValueError, match="operator_panel_required"):
        control._validate_transfer(command)
    command.update(source="manual", execution_context="panel")
    with pytest.raises(ValueError, match="panel_owner_mismatch"):
        control._validate_transfer(command)
    command["panel_id"] = "panel"
    with pytest.raises(ValueError, match="navigation_journey_new_start_required"):
        control._validate_transfer(command)
    assert gate.lease_deadline == 3.0
    assert gate.owner == "navigation"
    assert control.state == "idle"
