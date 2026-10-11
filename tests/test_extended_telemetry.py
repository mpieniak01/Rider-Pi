import struct

import pytest

from apps.motion.sensor_quality import SensorSamples, projected_samples
from drivers.xgo.telemetry import decode_imu_packet


def test_confirmed_packet():
    packet = decode_imu_packet(bytes.fromhex("cd9cf53ecdec53be006c1b413da43940150a34bf0bb49f40"))
    assert packet["accel_z"] == pytest.approx(9.713867, abs=0.001)
    assert packet["roll"] == pytest.approx(2.900649, abs=0.001)


@pytest.mark.parametrize("payload", [b"", bytes(23), struct.pack("<6f", float("nan"), 0, 0, 0, 0, 0)])
def test_invalid_packet(payload):
    with pytest.raises(ValueError):
        decode_imu_packet(payload)


def test_optional_channels_do_not_gate_required_measurements():
    samples = SensorSamples(lambda: 100, lambda: 1000)
    for name, value in {"roll": 1, "pitch": 2, "yaw": 3, "battery": 0.3}.items():
        samples.observe(name, value)
    samples.observe("accel_x", None)
    samples.observe("work_status", 0)
    assert samples.quality()["ready"]
    values, rows = projected_samples(samples.payload("R-1.1.6"), now=1000)
    assert values["work_status"] == 0
    assert rows["work_status"]["unit"] == "code"
    assert values["accel_x"] is None


def test_acceleration_projection():
    samples = SensorSamples(lambda: 100, lambda: 1000)
    for name in ("roll", "pitch", "yaw", "accel_x", "accel_y", "accel_z"):
        samples.observe(name, 1.25)
    samples.observe("battery", 0.3)
    values, rows = projected_samples(samples.payload(), now=1000)
    assert values["accel_z"] == 1.25
    assert rows["accel_z"]["unit"] == "m/s^2"


def test_extended_adapter_response_mode_and_status():
    from drivers.xgo.adapter import XgoAdapter

    class Dog:
        rx_TYPE = 0x12
        rx_data = bytes([0])

        def _XGO__read(self, address, read_len):
            assert (address, read_len) == (0x02, 1)

        def _XGO__unpack(self):
            return True

    adapter = XgoAdapter.__new__(XgoAdapter)
    adapter._dog = Dog()
    adapter.error = None
    assert adapter.read_extended_sensor("work_status") == 0
    adapter._dog.rx_TYPE = 0x01
    assert adapter.read_extended_sensor("work_status") is None
