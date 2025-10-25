#!/usr/bin/env python3
"""Tests for Google Home API integration."""

from __future__ import annotations

import pytest

from services.api_core import google_home_api


def test_get_devices():
    """Test that get_devices returns a list of devices."""
    devices = google_home_api.get_devices()
    assert isinstance(devices, list)
    assert len(devices) > 0

    # Check first device has required fields
    device = devices[0]
    assert "id" in device
    assert "name" in device
    assert "type" in device
    assert "traits" in device
    assert "state" in device
    assert "attributes" in device


def test_onoff_command():
    """Test OnOff command."""
    # Turn on
    result = google_home_api.send_command("light_1", "action.devices.commands.OnOff", {"on": True})
    assert result["ok"] is True
    assert result["state"]["on"] is True

    # Turn off
    result = google_home_api.send_command("light_1", "action.devices.commands.OnOff", {"on": False})
    assert result["ok"] is True
    assert result["state"]["on"] is False


def test_brightness_command():
    """Test BrightnessAbsolute command."""
    result = google_home_api.send_command("light_1", "action.devices.commands.BrightnessAbsolute", {"brightness": 75})
    assert result["ok"] is True
    assert result["state"]["brightness"] == 75

    # Test invalid brightness
    result = google_home_api.send_command("light_1", "action.devices.commands.BrightnessAbsolute", {"brightness": 150})
    assert result["ok"] is False


def test_color_temp_command():
    """Test ColorAbsolute command with temperature."""
    result = google_home_api.send_command(
        "light_1", "action.devices.commands.ColorAbsolute", {"color": {"temperatureK": 4000}}
    )
    assert result["ok"] is True
    assert result["state"]["color"]["temperatureK"] == 4000

    # Test out of range temperature
    result = google_home_api.send_command(
        "light_1", "action.devices.commands.ColorAbsolute", {"color": {"temperatureK": 10000}}
    )
    assert result["ok"] is False


def test_color_rgb_command():
    """Test ColorAbsolute command with RGB."""
    result = google_home_api.send_command(
        "light_1", "action.devices.commands.ColorAbsolute", {"color": {"spectrumRgb": 0xFF0000}}
    )
    assert result["ok"] is True
    assert result["state"]["color"]["spectrumRgb"] == 0xFF0000


def test_thermostat_setpoint_command():
    """Test ThermostatTemperatureSetpoint command."""
    result = google_home_api.send_command(
        "thermostat_1", "action.devices.commands.ThermostatTemperatureSetpoint", {"thermostatTemperatureSetpoint": 22.5}
    )
    assert result["ok"] is True
    assert result["state"]["thermostatTemperatureSetpoint"] == 22.5


def test_thermostat_mode_command():
    """Test ThermostatSetMode command."""
    result = google_home_api.send_command(
        "thermostat_1", "action.devices.commands.ThermostatSetMode", {"thermostatMode": "cool"}
    )
    assert result["ok"] is True
    assert result["state"]["thermostatMode"] == "cool"

    # Test invalid mode
    result = google_home_api.send_command(
        "thermostat_1", "action.devices.commands.ThermostatSetMode", {"thermostatMode": "invalid"}
    )
    assert result["ok"] is False


def test_startstop_command():
    """Test StartStop command."""
    # Start
    result = google_home_api.send_command("vacuum_1", "action.devices.commands.StartStop", {"start": True})
    assert result["ok"] is True
    assert result["state"]["isRunning"] is True

    # Stop
    result = google_home_api.send_command("vacuum_1", "action.devices.commands.StartStop", {"start": False})
    assert result["ok"] is True
    assert result["state"]["isRunning"] is False


def test_dock_command():
    """Test Dock command."""
    result = google_home_api.send_command("vacuum_1", "action.devices.commands.Dock", {})
    assert result["ok"] is True
    assert result["state"]["isRunning"] is False
    assert result["state"]["isDocked"] is True


def test_device_not_found():
    """Test sending command to non-existent device."""
    result = google_home_api.send_command("invalid_device", "action.devices.commands.OnOff", {"on": True})
    assert result["ok"] is False
    assert "error" in result


def test_unsupported_trait():
    """Test sending command requiring unsupported trait."""
    result = google_home_api.send_command(
        "thermostat_1", "action.devices.commands.BrightnessAbsolute", {"brightness": 50}
    )
    assert result["ok"] is False
    assert "error" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
