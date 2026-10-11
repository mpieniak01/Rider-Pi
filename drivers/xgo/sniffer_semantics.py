"""Offline meaning of observed bytes; never infers physical completion."""

import math
import struct

from drivers.xgo.telemetry import decode_imu_packet

REGISTERS = {
    0x01: "BATTERY",
    0x02: "WORK_STATUS",
    0x03: "PERFORM",
    0x04: "CALIBRATION",
    0x05: "UPGRADE",
    0x06: "SET_ORIGIN",
    0x20: "LOAD_UNLOAD_MOTORS",
    0x21: "TEACH_RECORD",
    0x22: "TEACH_PLAY",
    0x07: "FIRMWARE_VERSION",
    0x30: "VX",
    0x31: "VY",
    0x32: "VYAW",
    0x35: "HEIGHT",
    0x36: "ROLL_SETPOINT",
    0x39: "PERIODIC_ROLL",
    0x3E: "ACTION",
    0x5C: "MOTOR_SPEED",
    0x61: "BALANCE",
    0x62: "ROLL",
    0x63: "PITCH",
    0x64: "YAW",
    0x65: "IMU_PACKET",
    0x66: "ROLL_INTEGER",
    0x67: "PITCH_INTEGER",
    0x68: "YAW_INTEGER",
    0x82: "PERIODIC_HEIGHT",
}
ACTIONS = {
    1: "sway_left_right",
    2: "raise_lower",
    3: "forward_backward",
    4: "snake",
    5: "lift_rotate",
    6: "circular_sway",
    255: "reset_posture",
}


def meaning(frame, firmware=None):
    direction, mode = frame["direction"], frame["mode"]
    address = frame["address"]
    payload = bytes.fromhex(frame["payload_hex"])
    result = {"register": REGISTERS.get(address, "unknown"), "physical_completion": "unverified"}
    if direction == "tx" and mode == 0x02:
        return {
            **result,
            "kind": "read_request",
            "requested_bytes": payload[0] if len(payload) == 1 else None,
            "valid": len(payload) == 1 and 0 < payload[0] <= 50,
        }
    if direction == "rx":
        result["kind"] = "read_response" if mode == 0x12 else "unknown_receive"
        if mode != 0x12:
            return result
        result["value"] = None
        if address == 0x07:
            try:
                result.update(value=payload.decode("ascii").strip("\x00"), unit="text")
            except UnicodeDecodeError:
                result["decode_error"] = "invalid_firmware_text"
        elif firmware == "R-1.1.6":
            try:
                if address == 0x65:
                    result.update(
                        value=decode_imu_packet(payload),
                        units={"acceleration": "m/s^2", "angles": "degrees"},
                        includes_gravity=True,
                    )
                elif address in {0x62, 0x63, 0x64} and len(payload) == 4:
                    value = struct.unpack("<f", payload)[0]
                    if not math.isfinite(value):
                        raise ValueError("nonfinite_angle")
                    result.update(value=value, unit="degrees")
                elif address in {0x66, 0x67, 0x68} and len(payload) == 2:
                    result.update(value=struct.unpack(">h", payload)[0], unit="integer_angle")
                elif address == 0x01 and len(payload) == 1 and payload[0] <= 100:
                    result.update(value=payload[0], unit="percent")
                elif address == 0x02 and len(payload) == 1 and payload[0] in {0, 1}:
                    result.update(value=payload[0], unit="code", label="normal" if payload[0] else "fallen")
            except (ValueError, struct.error) as exc:
                result["decode_error"] = str(exc)
        else:
            result["decode_status"] = "firmware_format_unconfirmed"
        return result
    if direction != "tx" or mode != 0x01:
        return {**result, "kind": "unknown"}
    result.update(kind="write_command", acknowledgement="not_observed_by_this_frame")
    if len(payload) != 1:
        return {**result, "decode_status": "payload_format_unconfirmed"}
    value = payload[0]
    result.update(value=value, unit="command_byte")
    if address in {0x30, 0x31, 0x32}:
        result.update(neutral=value == 128, signed_byte_offset=value - 128, physical_velocity="unmeasured")
    elif address == 0x3E:
        result.update(
            action_id=value,
            documented_name=ACTIONS.get(value, "unknown"),
            action_table="manufacturer_documentation_not_physically_verified",
            execution="controller_firmware",
            calibration_effect="not_encoded_in_command",
        )
    elif address in {0x03, 0x61}:
        result.update(enabled=bool(value) if value in {0, 1} else None)
    elif address in {0x39, 0x82}:
        result.update(
            generator="controller_firmware",
            enabled=value != 0,
            period_sdk_s=1 + (value - 1) / 254 if value else 0,
            interpretation="installed_sdk_mapping_not_feedback",
        )
    elif address in {0x35, 0x36}:
        result.update(
            sdk_setpoint=60 + value * 60 / 255 if address == 0x35 else -17 + value * 34 / 255,
            sdk_unit="mm" if address == 0x35 else "degrees",
            interpretation="installed_sdk_mapping_not_feedback",
        )
    return result
