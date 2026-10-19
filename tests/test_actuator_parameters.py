"""Posture descriptors and all three validation layers; no hardware access."""

import pytest

from apps.motion import manual_settings
from apps.motion.actuator_contract import validate_actuator
from common.actuator_parameters import HEIGHT_MAX, HEIGHT_MIN, posture_parameters
from drivers.xgo.adapter import XgoAdapter
from services.safety_contract import command_envelope


def test_descriptors_share_device_bounds_and_do_not_claim_millimeters():
    descriptors = posture_parameters()
    height = descriptors["height"]
    assert (height["minimum"], height["maximum"]) == (HEIGHT_MIN, HEIGHT_MAX)
    assert height["unit"] == "sdk_height_command"
    assert height["display_factor"] == 1
    assert height["step"] == 1
    assert "physical_measurement" in height["meaning"]
    assert "full_balance_shutdown" in descriptors["balance"]["meaning"]
    assert manual_settings.parameter_schema()["actuator_fields"] == descriptors
    height["minimum"] = 0
    assert posture_parameters()["height"]["minimum"] == HEIGHT_MIN


def test_read_only_adapter_exposes_descriptors_without_uart():
    adapter = XgoAdapter()
    assert not adapter.ok()
    for name, descriptor in posture_parameters().items():
        capability = adapter.capabilities()[name]
        assert capability["parameter"] == descriptor
        assert capability["available"] is False


@pytest.mark.parametrize("height", [HEIGHT_MIN, 95, HEIGHT_MAX])
def test_shared_bounds_accept_valid_integer_height(height):
    assert validate_actuator({"action": "height", "height": height}) == {"height": height}


@pytest.mark.parametrize("height", [True, 74, 116, 75.5, float("nan")])
def test_shared_bounds_refuse_invalid_height(height):
    with pytest.raises(ValueError):
        validate_actuator({"action": "height", "height": height})


def test_http_uses_same_bounds(monkeypatch):
    import services.safety_contract as contract

    monkeypatch.setattr(contract.time, "time", lambda: 100)
    body = {
        "action": "height",
        "height": HEIGHT_MAX,
        "generation": "fixture",
        "seq": 1,
        "request_id": "fixture",
        "source": "manual",
        "ts": 100,
        "ttl_ms": 500,
    }
    assert command_envelope(body)["height"] == HEIGHT_MAX
    with pytest.raises(ValueError):
        command_envelope({**body, "height": HEIGHT_MAX + 1})
