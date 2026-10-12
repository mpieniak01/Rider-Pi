"""Fake transport only. No SDK, UART, or motion."""

import importlib.util
import json
import time
from pathlib import Path

import pytest

from drivers.xgo import sniffer

spec = importlib.util.spec_from_file_location("uart_sniffer_cli", Path(__file__).parents[1] / "scripts/uart_sniffer.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class FakeSerial:
    timeout = None

    def __init__(self):
        self.closed = False

    def write(self, data):
        return len(data) - 1

    def read(self, size=1):
        return b"abc"[:size]

    def flushInput(self):
        pass

    reset_input_buffer = flushInput

    def close(self):
        self.closed = True


@pytest.fixture
def capture(tmp_path, monkeypatch):
    monkeypatch.setattr(sniffer, "runtime_directory", lambda: tmp_path)
    monkeypatch.setattr(cli, "runtime_directory", lambda: tmp_path)
    recorder = sniffer.Capture()
    yield recorder
    recorder.close()


def wait_until(predicate):
    until = time.monotonic() + 2
    while not predicate():
        assert time.monotonic() < until
        time.sleep(0.01)


def test_attach_detach_and_transparent_transport(capture):
    native = FakeSerial()
    tap = sniffer.SerialTap(native, capture)
    assert tap.write(b"off") == 2
    assert capture.output is None
    response = cli.control(capture.status()["pid"], "attach")
    assert response["active"]
    tap.timeout = 0.03
    assert native.timeout == 0.03
    assert tap.write([1, 2, 3]) == 2
    assert tap.read(2) == b"ab"
    tap.flushInput()
    wait_until(lambda: capture.events.empty())
    response = cli.control(capture.status()["pid"], "detach")
    assert not response["active"]
    rows = [json.loads(line) for line in Path(response["file"]).read_text().splitlines()]
    assert any(r.get("direction") == "tx" and r["hex"] == "0102" for r in rows)
    assert any(r.get("direction") == "rx" and r["hex"] == "6162" for r in rows)
    assert any(r.get("direction") == "gap" for r in rows)
    before = Path(response["file"]).read_text()
    tap.write(b"off")
    assert Path(response["file"]).read_text() == before
    tap.close()
    assert native.closed


def test_capture_failure_does_not_break_serial():
    class Broken:
        def record(self, *args, **kwargs):
            raise OSError("disk failed")

        def close(self):
            raise OSError("disk failed")

    native = FakeSerial()
    tap = sniffer.SerialTap(native, Broken())
    assert tap.write(b"abc") == 2
    assert tap.read() == b"a"
    tap.flushInput()
    tap.close()
    assert native.closed


def test_duration_and_size_limits(capture):
    capture._command({"action": "attach", "seconds": 1, "max_bytes": 4096})
    for _ in range(20):
        capture.record("rx", b"x" * 128)
    wait_until(lambda: not capture.active)
    assert Path(capture.output).stat().st_size <= 4096
    capture._command({"action": "attach", "seconds": 1})
    wait_until(lambda: not capture.active)
    assert "time_limit" in Path(capture.output).read_text()


def test_invalid_control_and_reconnect(capture):
    with pytest.raises(ValueError):
        capture._command({"action": "attach", "seconds": 301})
    assert not capture.active
    cli.control(capture.status()["pid"], "attach")
    with pytest.raises(RuntimeError, match="already_attached"):
        cli.control(capture.status()["pid"], "attach")
    cli.control(capture.status()["pid"], "detach")
    first = capture.output
    cli.control(capture.status()["pid"], "attach")
    assert capture.output != first


def test_frame_decoder_chunking_checksum_and_gap():
    frame = bytes([0x55, 0, 9, 1, 0x30, 128, 255 - (9 + 1 + 0x30 + 128) % 256, 0, 0xAA])
    rows = list(
        cli.decode(
            [
                {"direction": "tx", "hex": frame[:4].hex(), "time_ns": 1},
                {"direction": "tx", "hex": frame[4:].hex(), "time_ns": 2},
                {"direction": "rx", "hex": frame[:4].hex()},
                {"direction": "gap", "cause": "flushInput"},
            ]
        )
    )
    decoded = [r for r in rows if r.get("event") == "frame"]
    assert len(decoded) == 1
    assert decoded[0]["name"] == "VX"
    assert decoded[0]["payload_hex"] == "80"
    bad = bytearray(frame)
    bad[-3] = 0
    assert any(r.get("event") == "invalid_frame" for r in cli.decode([{"direction": "rx", "hex": bad.hex()}]))


@pytest.mark.parametrize("value", [None, "0", "", "false", "true", "invalid"])
def test_disabled_install_keeps_native_transport_without_capture(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("RIDER_UART_SNIFFER_ENABLED", raising=False)
    else:
        monkeypatch.setenv("RIDER_UART_SNIFFER_ENABLED", value)

    def forbidden_capture():
        raise AssertionError("Disabled sniffer must not create a worker, socket or queue")

    monkeypatch.setattr(sniffer, "Capture", forbidden_capture)
    native = FakeSerial()
    assert sniffer.install(native) is native
    assert native.write(b"abc") == 2
    assert native.read(2) == b"ab"
    assert not native.closed


def test_enabled_install_preserves_attach_and_detach(monkeypatch, capture):
    monkeypatch.setenv("RIDER_UART_SNIFFER_ENABLED", "1")
    monkeypatch.setattr(sniffer, "Capture", lambda: capture)
    native = FakeSerial()
    tap = sniffer.install(native)
    assert isinstance(tap, sniffer.SerialTap)
    assert tap._capture is capture
    assert not capture.active
    assert cli.control(capture.status()["pid"], "attach")["active"]
    assert tap.write(b"abc") == 2
    assert not cli.control(capture.status()["pid"], "detach")["active"]
    tap.close()
    assert native.closed


def test_enabled_install_failure_keeps_native_transport(monkeypatch):
    monkeypatch.setenv("RIDER_UART_SNIFFER_ENABLED", "1")

    def broken_capture():
        raise OSError("socket unavailable")

    monkeypatch.setattr(sniffer, "Capture", broken_capture)
    native = FakeSerial()
    assert sniffer.install(native) is native
    assert not native.closed
