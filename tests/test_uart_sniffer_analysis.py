"""Offline bytes only; never imports SDK or opens a serial device."""

import struct

import pytest
from test_uart_sniffer import cli

from drivers.xgo.sniffer_analysis import analyze, markdown
from drivers.xgo.sniffer_semantics import meaning


def frame(direction, address, payload, mode=None, at=0):
    mode = mode if mode is not None else 0x01 if direction == "tx" else 0x12
    return {
        "event": "frame",
        "direction": direction,
        "address": address,
        "mode": mode,
        "payload_hex": payload.hex(),
        "time_ns": at,
    }


def test_read_request_is_not_a_write_and_zero_status_is_preserved():
    request = frame("tx", 2, b"\x01", mode=2)
    response = frame("rx", 2, b"\x00", at=5_000_000)
    result = analyze([request, response], firmware="R-1.1.6")
    assert result["transactions"][0]["latency_ms"] == 5
    assert result["transactions"][0]["value"] == 0
    assert result["command_changes"] == []
    assert result["work_status_changes"][0]["label"] == "fallen"


def test_actions_are_commands_not_completion():
    row = meaning(frame("tx", 0x3E, b"\x05"))
    assert row["action_id"] == 5
    assert row["execution"] == "controller_firmware"
    assert row["physical_completion"] == "unverified"
    assert row["calibration_effect"] == "not_encoded_in_command"


def test_generators_and_setpoints_do_not_claim_feedback():
    assert meaning(frame("tx", 0x82, b"\x00"))["enabled"] is False
    assert meaning(frame("tx", 0x39, b"\xff"))["period_sdk_s"] == 2
    height = meaning(frame("tx", 0x35, b"\x80"))
    assert height["sdk_setpoint"] == pytest.approx(90.117647)
    assert height["interpretation"] == "installed_sdk_mapping_not_feedback"


def test_imu_format_requires_confirmed_firmware():
    row = frame("rx", 0x65, struct.pack("<6f", 1, 2, 9.8, 3, 4, 5))
    assert meaning(row)["value"] is None
    decoded = meaning(row, "R-1.1.6")
    assert decoded["value"]["roll"] == 3
    assert decoded["includes_gravity"]
    assert "gyro" not in decoded["value"]


def test_nonfinite_and_short_imu_are_not_measurements():
    for data in (bytes(23), struct.pack("<6f", float("nan"), 0, 0, 0, 0, 0)):
        assert meaning(frame("rx", 0x65, data), "R-1.1.6").get("decode_error")


def test_wrong_response_length_cannot_match_request():
    report = analyze([frame("tx", 0x65, b"\x18", mode=2), frame("rx", 0x65, bytes(4), at=1_000_000)])
    assert report["fault_counts"]["unmatched_response"] == 1
    assert report["transactions"][0]["outcome"] == "capture_ended_before_response"


def test_timeout_and_gap_are_distinct():
    request = frame("tx", 1, b"\x01", mode=2)
    report = analyze([request, {"direction": "gap", "time_ns": 1_000_000}])
    assert report["transactions"][0]["outcome"] == "observation_gap"
    assert not report["capture_loss_observed"]
    report = analyze([request, frame("rx", 1, b"\x1e", at=200_000_000)])
    assert report["transactions"][0]["outcome"] == "no_response_within_observation_window"
    assert report["fault_counts"]["unmatched_response"] == 1


def test_firmware_is_inferred_without_decoding_unknown_packets():
    events = [frame("rx", 7, b"R-1.1.6\x00"), frame("rx", 2, b"\x01")]
    assert analyze(events)["timeline"][1]["semantic"]["value"] == 1


def test_command_changes_keep_repetitions_in_frame_counts():
    rows = [frame("tx", 0x30, bytes([value]), at=i * 20_000_000) for i, value in enumerate([128, 128, 150, 150, 128])]
    report = analyze(rows)
    assert report["frame_counts"]["tx:VX"] == 5
    assert len(report["command_changes"]) == 3
    assert report["write_intervals"]["VX"]["median_ms"] == 20
    assert "Internal motor traffic" in markdown(report)


def test_decoder_first_last_chunk_times():
    data = bytes.fromhex("55 00 09 01 3e 01 b6 00 aa")
    events = list(
        cli.decode(
            [
                {"direction": "tx", "hex": data[:4].hex(), "time_ns": 10},
                {"direction": "tx", "hex": data[4:].hex(), "time_ns": 20},
            ],
            firmware="R-1.1.6",
        )
    )
    assert events[0]["first_time_ns"] == 10
    assert events[0]["time_ns"] == 20
    assert events[0]["semantic"]["action_id"] == 1


def test_capture_loss_is_visible():
    report = analyze([{"event": "end", "dropped": 2}])
    assert report["capture_loss_observed"]


def test_identical_overlapping_reads_have_ambiguous_pairing():
    events = [
        frame("tx", 1, bytes([1]), mode=2, at=0),
        frame("tx", 1, bytes([1]), mode=2, at=1_000_000),
        frame("rx", 1, bytes([30]), at=2_000_000),
    ]
    report = analyze(events, firmware="R-1.1.6")
    assert report["transactions"][0]["outcome"] == "response_observed_pairing_ambiguous"
    assert report["transactions"][0]["pairing"] == "ambiguous_same_address_length"


def test_external_export_provenance_is_explicit():
    report = analyze([], source="wire_export")
    assert report["source"] == "wire_export"
    assert report["source_declared_by_operator"]
    with pytest.raises(ValueError):
        analyze([], source="magic_firmware_probe")


def test_normal_flush_is_a_continuity_gap_not_capture_failure():
    report = analyze([{"direction": "gap", "cause": "flushInput", "time_ns": 1}])
    assert report["continuity_gaps"] == 1
    assert report["fault_counts"] == {}
    assert not report["capture_loss_observed"]


def test_truncated_capture_cannot_hide_loss():
    report = analyze([{"event": "gap", "direction": "rx", "cause": "capture_truncated"}])
    assert report["capture_loss_observed"]


def test_invalid_hex_does_not_crash_offline_decoder():
    rows = list(cli.decode([{"direction": "tx", "hex": "zz", "time_ns": 1}]))
    assert rows[0]["event"] == "invalid_capture_hex"
