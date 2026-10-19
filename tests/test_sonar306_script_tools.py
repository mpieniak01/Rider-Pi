"""Packet 20 fixtures never open UART, HTTP, hardware drivers or a service process."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def script(name):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location("sonar306_" + path.stem.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    previous = sys.path[:]
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = previous
    return module


@pytest.fixture
def decoder():
    return script("uart_sniffer.py")


def packet(payload=b"\x01"):
    data = bytes([len(payload) + 8, 1, 0x10]) + payload
    return b"\x55\x00" + data + bytes([255 - sum(data) % 256, 0, 170])


@pytest.mark.parametrize("split", range(1, 9))
def test_offline_decoder_preserves_original_first_and_last_chunk_times(decoder, split):
    frame = packet()
    rows = [
        {"direction": "rx", "hex": frame[:split].hex(), "time_ns": 111},
        {"direction": "rx", "hex": frame[split:].hex(), "time_ns": 222},
    ]
    result = list(decoder.decode(rows))
    assert len(result) == 1
    assert result[0]["event"] == "frame"
    assert result[0]["first_time_ns"] == 111
    assert result[0]["time_ns"] == 222
    assert result[0]["timestamp"] == "host_serial_chunks_not_wire"
    assert result[0]["payload_hex"] == "01"
    assert result[0]["checksum_valid"] is True


def test_capture_boundary_flush_order_and_invalid_hex_remain_visible(decoder):
    rows = [
        {"direction": "tx", "hex": "55", "time_ns": 1},
        {"direction": "rx", "hex": "5500", "time_ns": 2},
        {"event": "end", "time_ns": 3},
        {"direction": "rx", "hex": None, "time_ns": 4},
    ]
    result = list(decoder.decode(rows))
    assert [row["event"] for row in result] == ["partial_frame", "partial_frame", "end", "invalid_capture_hex"]
    assert [row.get("direction") for row in result] == ["tx", "rx", None, "rx"]


def test_corrupted_or_truncated_capture_never_becomes_a_valid_frame(decoder):
    bad = bytearray(packet())
    bad[-3] ^= 1
    result = list(decoder.decode([{"direction": "rx", "hex": bad.hex(), "time_ns": 1}]))
    assert any(row["event"] == "invalid_frame" for row in result)
    assert all(row["event"] != "frame" for row in result)
    truncated = list(decoder.decode([{"direction": "rx", "hex": "550009", "truncated": True, "time_ns": 2}]))
    assert truncated == [{"event": "gap", "direction": "rx", "cause": "capture_truncated"}]


def test_offline_analysis_writes_only_explicit_output_arguments(decoder, tmp_path, monkeypatch):
    capture = tmp_path / "fixture.jsonl"
    capture.write_text(json.dumps({"direction": "rx", "hex": packet().hex(), "time_ns": 1}) + "\n")
    calls = []
    monkeypatch.setattr(decoder, "analyze", lambda events, **kwargs: {"events": len(list(events)), **kwargs})
    monkeypatch.setattr(decoder, "markdown", lambda report: "fixture report")
    monkeypatch.setattr(decoder, "write_output", lambda path, data: calls.append((path, data)))
    args = SimpleNamespace(
        file=capture,
        firmware=None,
        action="analyze",
        response_timeout_ms=100,
        source="serial_calls",
        output=tmp_path / "report.json",
        markdown=tmp_path / "report.md",
    )
    decoder._offline_capture(args)
    assert [path for path, _ in calls] == [args.output, args.markdown]
    assert json.loads(calls[0][1])["events"] == 1
    assert calls[1][1] == b"fixture report"


def test_led_blink_cleanup_restores_signal_before_conditional_off(monkeypatch):
    led = script("sys_led-control.py")
    events = []

    class Wait:
        def wait(self):
            events.append("wait")
            raise KeyboardInterrupt

        def set(self):
            pass

    monkeypatch.setattr(led, "Event", Wait)
    monkeypatch.setattr(led.signal, "getsignal", lambda _: "previous fixture")
    monkeypatch.setattr(led.signal, "signal", lambda _, handler: events.append(("signal", handler)))
    client = SimpleNamespace(request=lambda path, method, body: events.append(("off", path, method, body)))
    result = {"ok": True, "data": {"generation": "g", "name": "fixture-led"}}
    with pytest.raises(KeyboardInterrupt):
        led._wait_for_blink_stop(client, "/fixture/led", result)
    assert events[-2] == ("signal", "previous fixture")
    assert events[-1] == ("off", "/fixture/led", "POST", {"action": "off", "name": "fixture-led", "if_generation": "g"})


@pytest.mark.parametrize("hz", [0, -1, 501, float("inf"), float("nan")])
def test_led_frequency_is_validated_before_any_request(hz):
    led = script("sys_led-control.py")
    args = SimpleNamespace(action="blink", hz=hz, on_ms=None, off_ms=None)
    with pytest.raises(ValueError, match="invalid_led_frequency"):
        led._blink_delays(args, {})


def test_led_explicit_durations_and_boundary_frequency_are_preserved():
    led = script("sys_led-control.py")
    args = SimpleNamespace(action="blink", hz=500, on_ms=7, off_ms=None)
    body = {}
    led._blink_delays(args, body)
    assert body == {"on_ms": 7, "off_ms": 1}


def test_manual_probe_automated_guard_precedes_every_api_call(monkeypatch, capsys):
    probe = script("manual_motion-probe.py")
    monkeypatch.setenv("RIDER_TEST_ISOLATED", "1")
    monkeypatch.setattr(
        sys,
        "argv",
        ["manual_motion-probe.py", "--action", "move", "--duration", ".1", "--plan", "fixture must not execute"],
    )
    monkeypatch.setattr(
        probe, "request_json", lambda *_args, **_kwargs: pytest.fail("No API call from automated probe")
    )
    assert probe.main() == 2
    assert "Physical probes forbidden" in capsys.readouterr().err


@pytest.mark.parametrize(
    "patch",
    [
        {"plan": " "},
        {"duration": 0.251},
        {"vx": float("nan")},
        {"action": "height", "height": 74},
        {"action": "balance", "enabled": None},
    ],
)
def test_manual_validation_keeps_existing_plan_range_and_explicit_intent_rules(patch):
    probe = script("manual_motion-probe.py")
    values = {
        "plan": "fixture",
        "vx": 0,
        "yaw": 0,
        "duration": 0.1,
        "action": "move",
        "height": None,
        "enabled": None,
        "action_id": None,
    }
    values.update(patch)
    attempt = SimpleNamespace(**values)
    with pytest.raises(ValueError):
        probe._validate_attempt(attempt)


def test_panel_initialization_tries_only_until_one_fake_begin_succeeds(monkeypatch):
    panel = script("dev_panel-reset-safe.py")
    events = []

    class Device:
        SPI = SimpleNamespace(max_speed_hz=0)

        def begin(self):
            events.append("begin")
            raise OSError("fixture unavailable entrypoint")

        def Begin(self):
            events.append("Begin")

        def Init(self):
            pytest.fail("Initialization must stop after success")

    monkeypatch.setattr(panel, "pick_device_class", lambda: Device)
    dev = panel._initialize_device(SimpleNamespace(spi_hz=123))
    assert events == ["begin", "Begin"]
    assert dev.SPI.max_speed_hz == 123


def test_panel_fill_preserves_memory_write_and_exact_line_chunks(monkeypatch):
    panel = script("dev_panel-reset-safe.py")
    calls = []
    monkeypatch.setattr(panel, "cmd", lambda dev, value: calls.append(("command", dev, value)))
    monkeypatch.setattr(panel, "chunk_write", lambda dev, data: calls.append(("bytes", dev, data)))
    panel._fill565("inert-device", b"\xf8\x00", 2, 3)
    assert calls[0] == ("command", "inert-device", 0x2C)
    assert calls[1:] == [("bytes", "inert-device", b"\xf8\x00" * 2)] * 3


def test_document_rewrites_keep_skip_context_and_sequential_change_records(tmp_path, monkeypatch):
    updater = script("dev_update-docs-references.py")
    monkeypatch.setattr(updater, "REPO_ROOT", tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/new.py").write_text("fixture")
    (tmp_path / "Makefile").write_text("lcd-on:\n")
    content = "python3 ops/lcdctl.py on\nUse ops/old.py\nops/old.py → scripts/new.py\n"
    mappings = {r"python3 (\.\/)?ops/lcdctl\.py on": "make lcd-on", "ops/old.py": "scripts/new.py"}
    updated, changes = updater.update_file_references(content, mappings, tmp_path / "guide.md")
    assert updated == "make lcd-on\nUse scripts/new.py\nops/old.py → scripts/new.py\n"
    assert len(changes) == 2
    assert changes[0].startswith("Line 1:")
    assert changes[1] == "Line 2: ops/old.py → scripts/new.py"


def test_missing_document_target_retains_original_reference_and_warning(tmp_path, monkeypatch, capsys):
    updater = script("dev_update-docs-references.py")
    monkeypatch.setattr(updater, "REPO_ROOT", tmp_path)
    result = updater._replace_reference("ops/old.py", "ops/old.py", "scripts/missing.py", tmp_path / "guide.md", 7)
    assert result == ("ops/old.py", False)
    assert "guide.md line 7: File scripts/missing.py not found" in capsys.readouterr().err


def test_document_validation_retains_migration_exceptions_and_target_warnings(tmp_path, monkeypatch):
    validator = script("dev_validate-docs-links.py")
    monkeypatch.setattr(validator, "REPO_ROOT", tmp_path)
    file = tmp_path / "guide.md"
    file.write_text("[missing](absent.txt)\nops/old.py\nmake nonexistent\n")
    errors, warnings = validator.scan_markdown_file(file)
    assert errors == ["File not found: absent.txt"]
    assert set(warnings) == {"Legacy reference found: ops/old.py", "Makefile target not found: make nonexistent"}
    migration = tmp_path / "SCRIPTS_MIGRATION_SUMMARY.md"
    migration.write_text(file.read_text())
    errors, warnings = validator.scan_markdown_file(migration)
    assert errors == []
    assert warnings == ["Makefile target not found: make nonexistent"]


def test_legacy_import_audit_keeps_audio_directory_exception(tmp_path, monkeypatch):
    checker = script("dev_check-legacy-imports.py")
    file = tmp_path / "audio" / "fixture.py"
    file.parent.mkdir()
    file.write_text("fixture")
    monkeypatch.setattr(checker, "check_file_for_legacy_imports", lambda _: [(1, "fixture legacy", "blocked fixture")])
    monkeypatch.setattr(checker, "check_file_for_audio_imports", lambda _: pytest.fail("Audio directory is excluded"))
    failures, warnings = checker._inspect_imports(file, tmp_path)
    assert failures == [(Path("audio/fixture.py"), 1, "fixture legacy", "blocked fixture")]
    assert warnings == []
