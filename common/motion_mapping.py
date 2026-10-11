"""Command levels are not physical velocity measurements."""

MAPPING_ID = "rider-1.4.2-levels-v3"
LINEAR_LEVELS = 127
TURN_LEVELS = 180
LINEAR_SDK_LIMIT = 1.5


def linear_sdk_value(level):
    return level * LINEAR_SDK_LIMIT / LINEAR_LEVELS


def native_command_byte(value, limit):
    """Protocol neutral is 128; signed endpoints are 0 and 255."""
    fraction = max(-1.0, min(1.0, value / limit))
    scale = 127 if fraction >= 0 else 128
    return max(0, min(255, 128 + round(fraction * scale)))
