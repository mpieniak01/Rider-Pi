"""Decoder confirmed on Rider R-1.1.6; not the vendor mixed int16 decoder."""

import math
import struct

PACKET_FIELDS = ("accel_x", "accel_y", "accel_z", "roll", "pitch", "yaw")


def decode_imu_packet(payload):
    if not isinstance(payload, (bytes, bytearray)) or len(payload) != 24:
        raise ValueError("imu_packet_length")
    values = struct.unpack("<6f", payload)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("imu_packet_nonfinite")
    return dict(zip(PACKET_FIELDS, values))
