"""Binary parser and timeout fixtures with fake serial only; no hardware imports."""

from types import SimpleNamespace

import pytest

from drivers.xgo.adapter import guarded_sdk_class
from drivers.xgo.protocol import bound_serial, read_response


def frame(address=10, payload=b"\0\0\0\0", *, mode=3):
    size = len(payload) + 8
    checksum = 255 - (size + mode + address + sum(payload)) % 256
    return bytes([0x55, 0, size, mode, address]) + payload + bytes([checksum, 0, 0xAA])


class Serial:
    def __init__(self, data):
        self.data = data
        self.timeout = self.write_timeout = None

    def inWaiting(self):
        return len(self.data)

    def read(self, count):
        value, self.data = self.data[:count], self.data[count:]
        return value


def advancing_clock():
    state = SimpleNamespace(now=100.0, wall=1000.0)

    def clock():
        state.now += 0.001
        state.wall -= 10
        return state.now

    return state, clock


def parse(data, *, address=10, length=4):
    state, clock = advancing_clock()
    serial = Serial(data)
    result = read_response(
        serial, address=address, length=length, started_at=100, budget=0.03, clock=clock, sleep=lambda duration: None
    )
    return result, serial, state


def test_exact_axis_response_is_accepted_with_backwards_wall_clock():
    value, serial, clock = parse(frame())
    assert value["payload"] == b"\0\0\0\0"
    assert clock.wall < 1000 and serial.timeout == serial.write_timeout == 0.03


@pytest.mark.parametrize("data", [frame(address=11), frame(payload=b"\x50"), frame(payload=b"123456")])
def test_other_channel_or_payload_length_cannot_become_fresh_axis(data):
    with pytest.raises(TimeoutError, match="mismatch"):
        parse(data)


@pytest.mark.parametrize("data", [frame()[:-1] + b"\xff", frame()[:9] + b"\x11" + frame()[10:]])
def test_corrupt_complete_response_is_unknown(data):
    with pytest.raises(TimeoutError, match="corrupt"):
        parse(data)


def test_battery_length_is_one_payload_byte():
    value, _, _ = parse(frame(address=20, payload=b"\0"), address=20, length=1)
    assert value["payload"] == b"\0" and value["length"] == 9


def test_no_response_times_out_monotonically_while_wall_clock_moves_backwards():
    with pytest.raises(TimeoutError, match="timeout"):
        parse(b"")


def test_late_serial_read_is_unknown_even_with_valid_matching_frame():
    state = SimpleNamespace(now=100.0)
    serial = Serial(frame())
    original = serial.read

    def late(count):
        state.now += 0.1
        return original(count)

    serial.read = late
    with pytest.raises(TimeoutError, match="timeout"):
        read_response(serial, address=10, length=4, started_at=100, budget=0.03, clock=lambda: state.now)


def test_serial_timeout_failure_propagates_without_default_zero():
    serial = Serial(frame())

    def failed_read(count):
        raise TimeoutError("fake serial timeout")

    serial.read = failed_read
    with pytest.raises(TimeoutError, match="fake serial timeout"):
        read_response(serial, address=10, length=4, started_at=100, budget=0.03, clock=lambda: 100)


def test_unbounded_timeout_property_is_refused():
    class Unsupported:
        @property
        def timeout(self):
            return None

        @timeout.setter
        def timeout(self, value):
            pass

    with pytest.raises(RuntimeError, match="unbounded"):
        bound_serial(Unsupported(), 0.03)


def test_sdk_hook_resets_partial_parser_and_cannot_reuse_transaction(monkeypatch):
    class Vendor:
        def __init__(self):
            self.ser = Serial(frame())

        def _XGO__send(self, *args, **kw):
            pass

        def _XGO__read(self, addr, read_len=1):
            pass

        def _XGO__unpack(self, timeout=1):
            raise AssertionError("Vendor wall-clock parser must not run")

    _, clock = advancing_clock()
    monkeypatch.setattr("drivers.xgo.adapter.time.monotonic", clock)
    value = guarded_sdk_class(Vendor, SimpleNamespace(can_actuate=lambda: False))()
    value.rx_FLAG, value.rx_COUNT = 5, 3
    value._XGO__read(10, 4)
    assert value.rx_FLAG == value.rx_COUNT == 0
    assert value._XGO__unpack()
    with pytest.raises(TimeoutError, match="missing"):
        value._XGO__unpack()
