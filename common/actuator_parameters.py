"""Device-owned posture descriptors, shared by HTTP, executor and SDK validation."""

HEIGHT_MIN = 75
HEIGHT_MAX = 115

_HEIGHT = {
    "type": "integer",
    "unit": "sdk_height_command",
    "display_unit": "SDK",
    "display_factor": 1,
    "display_precision": 0,
    "minimum": HEIGHT_MIN,
    "maximum": HEIGHT_MAX,
    "step": 1,
    "meaning": "height_command_not_physical_measurement",
}
_BALANCE = {
    "type": "boolean",
    "unit": "enabled",
    "display_unit": "",
    "meaning": "roll_compensation_not_full_balance_shutdown",
}


def posture_parameters():
    """Copies prevent a client or adapter from modifying the shared definition."""
    return {"height": dict(_HEIGHT), "balance": dict(_BALANCE)}


def valid_height(value):
    return type(value) is int and HEIGHT_MIN <= value <= HEIGHT_MAX
