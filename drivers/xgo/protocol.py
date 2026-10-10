"""Bounded SDK 1.4.2 response framing on the sole owner's serial object."""

import time


def bound_serial(serial, budget):
    for field in ("timeout", "write_timeout"):
        current = getattr(serial, field, None)
        setattr(serial, field, budget if current is None or current > budget else current)
        value = getattr(serial, field)
        if type(value) not in (int, float) or not 0 <= value <= budget:
            raise RuntimeError("serial_timeout_unbounded")


def read_response(serial, *, address, length, started_at, budget, clock=time.monotonic, sleep=time.sleep):
    """Validate complete frames within a monotonic request budget.

    The installed protocol has no request ID. Matching address/length cannot
    distinguish two delayed identical transactions; do not claim that guarantee.
    """
    bound_serial(serial, budget)
    pending = bytearray()
    while 0 <= clock() - started_at < budget:
        available = serial.inWaiting()
        if type(available) is not int or available < 0:
            raise OSError("invalid_serial_available")
        if not available:
            sleep(min(0.001, max(0.0, budget - (clock() - started_at))))
            continue
        data = serial.read(min(available, 128))
        if not isinstance(data, (bytes, bytearray)):
            raise OSError("invalid_serial_payload")
        pending.extend(data)
        while len(pending) >= 2:
            offset = pending.find(b"\x55\x00")
            if offset < 0:
                pending[:] = pending[-1:] if pending[-1] == 0x55 else b""
                break
            if offset:
                del pending[:offset]
            if len(pending) < 3:
                break
            size = pending[2]
            if not 9 <= size <= 58:
                del pending[:2]
                continue
            if len(pending) < size:
                break
            frame = bytes(pending[:size])
            del pending[:size]
            payload = frame[5:-3]
            checksum = 255 - (sum(frame[2:5]) + sum(payload)) % 256
            if frame[-2:] != b"\x00\xaa" or frame[-3] != checksum:
                raise TimeoutError("sensor_response_corrupt")
            if frame[4] != address or size != length + 8 or len(payload) != length:
                raise TimeoutError("sensor_response_mismatch")
            if not 0 <= clock() - started_at <= budget:
                raise TimeoutError("sensor_read_timeout")
            return {"address": address, "length": size, "type": frame[3], "payload": payload}
    raise TimeoutError("sensor_read_timeout")
