#!/usr/bin/env python3
"""Control a tap in an existing process, or decode an offline capture. No UART access."""

from __future__ import annotations

import argparse
import json
import socket
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from drivers.xgo.sniffer import runtime_directory
from drivers.xgo.sniffer_analysis import analyze, markdown
from drivers.xgo.sniffer_semantics import REGISTERS, meaning
from services.core.cli_files import write_output


def control(pid, action, seconds=60):
    if pid <= 0:
        raise ValueError("positive_pid_required")
    with tempfile.TemporaryDirectory(prefix="client-", dir=runtime_directory()) as folder:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            client.bind(str(Path(folder) / "reply.sock"))
            client.settimeout(2)
            client.sendto(
                json.dumps({"action": action, "seconds": seconds}).encode(), str(runtime_directory() / f"{pid}.sock")
            )
            result = json.loads(client.recv(4096))
            if result.get("command_error"):
                raise RuntimeError(result["command_error"])
            return result
        finally:
            client.close()


def _flush_pending(buffers, starts):
    for name, pending in buffers.items():
        if pending:
            yield {"event": "partial_frame", "direction": name, "hex": pending.hex()}
            pending.clear()
        starts[name] = None


def _align_pending(pending, direction):
    offset = pending.find(bytes([0x55, 0x00]))
    if offset < 0:
        yield {"event": "unframed", "direction": direction, "hex": pending.hex()}
        pending[:] = pending[-1:] if pending[-1:] == b"U" else b""
        return False
    if offset:
        yield {"event": "unframed", "direction": direction, "hex": pending[:offset].hex()}
        del pending[:offset]
    return True


def _decoded_frame(frame, direction, row, first_time, firmware):
    address = frame[4]
    decoded = {
        "event": "frame",
        "direction": direction,
        "time_ns": row.get("time_ns"),
        "first_time_ns": first_time,
        "timestamp": "host_serial_chunks_not_wire",
        "mode": frame[3],
        "address": address,
        "name": REGISTERS.get(address, "unknown"),
        "payload_hex": frame[5:-3].hex(),
        "hex": frame.hex(),
        "checksum_valid": True,
    }
    if firmware is not None:
        decoded["semantic"] = meaning(decoded, firmware)
    return decoded


def _decode_pending(pending, direction, row, starts, firmware):
    while len(pending) >= 3:
        if not (yield from _align_pending(pending, direction)):
            break
        if len(pending) < 3:
            break
        size = pending[2]
        if not 9 <= size <= 255:
            yield {"event": "invalid_length", "direction": direction, "length": size}
            del pending[0]
            continue
        if len(pending) < size:
            break
        frame = bytes(pending[:size])
        valid = frame[-2:] == bytes([0, 170]) and frame[-3] == 255 - sum(frame[2:-3]) % 256
        if not valid:
            yield {"event": "invalid_frame", "direction": direction, "hex": frame.hex()}
            del pending[0]
            continue
        del pending[:size]
        decoded = _decoded_frame(frame, direction, row, starts[direction], firmware)
        yield decoded
        starts[direction] = row.get("time_ns") if pending else None


def _extend_capture(pending, starts, direction, row):
    if not pending:
        starts[direction] = row.get("time_ns")
    try:
        pending.extend(bytes.fromhex(row.get("hex", "")))
    except (ValueError, TypeError):
        pending.clear()
        starts[direction] = None
        return False
    return True


def decode(rows, *, firmware=None):
    starts = {"tx": None, "rx": None}
    buffers = {"tx": bytearray(), "rx": bytearray()}
    for row in rows:
        if row.get("event") in {"start", "end"}:
            yield from _flush_pending(buffers, starts)
            yield row
            continue
        direction = row.get("direction")
        if direction == "gap":
            buffers["rx"].clear()
            starts["rx"] = None
            yield row
            continue
        if direction not in buffers:
            yield row
            continue
        pending = buffers[direction]
        if not _extend_capture(pending, starts, direction, row):
            yield {"event": "invalid_capture_hex", "direction": direction, "time_ns": row.get("time_ns")}
            continue
        yield from _decode_pending(pending, direction, row, starts, firmware)
        if row.get("truncated"):
            pending.clear()
            yield {"event": "gap", "direction": direction, "cause": "capture_truncated"}
    for direction, pending in buffers.items():
        if pending:
            yield {"event": "partial_frame", "direction": direction, "hex": pending.hex()}


def _arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="action", required=True)
    subs.add_parser("list")
    for action in ("attach", "detach", "status"):
        cmd = subs.add_parser(action)
        cmd.add_argument("--pid", type=int, required=True)
        if action == "attach":
            cmd.add_argument("--seconds", type=int, default=60)
    for action in ("decode", "analyze"):
        cmd = subs.add_parser(action)
        cmd.add_argument("file", type=Path)
        cmd.add_argument("--firmware", help="Explicit controller format, e.g. R-1.1.6")
        if action == "analyze":
            cmd.add_argument("--output", type=Path)
            cmd.add_argument("--markdown", type=Path)
            cmd.add_argument("--response-timeout-ms", type=int, default=100)
            cmd.add_argument(
                "--source", choices=("serial_calls", "wire_export", "controller_bus_export"), default="serial_calls"
            )
    return parser.parse_args()


def _offline_capture(args):
    with args.file.open() as stream:
        events = decode((json.loads(line) for line in stream if line.strip()), firmware=args.firmware)
        if args.action == "decode":
            for row in events:
                print(json.dumps(row))
        else:
            report = analyze(
                events, firmware=args.firmware, response_timeout_ms=args.response_timeout_ms, source=args.source
            )
            content = json.dumps(report, indent=2)
            if args.output:
                write_output(args.output, (content + "\n").encode("utf-8"))
            else:
                print(content)
            if args.markdown:
                write_output(args.markdown, markdown(report).encode("utf-8"))


def main():
    args = _arguments()
    if args.action in {"decode", "analyze"}:
        _offline_capture(args)
    elif args.action == "list":
        print(
            json.dumps(
                {
                    "pids": sorted(
                        int(p.stem)
                        for p in runtime_directory().glob("*.sock")
                        if p.stem.isdigit() and Path(f"/proc/{p.stem}").exists()
                    )
                }
            )
        )
    else:
        print(json.dumps(control(args.pid, args.action, getattr(args, "seconds", 60))))


if __name__ == "__main__":
    main()
