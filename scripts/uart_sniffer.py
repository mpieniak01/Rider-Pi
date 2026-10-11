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


def decode(rows):
    buffers = {"tx": bytearray(), "rx": bytearray()}
    for row in rows:
        direction = row.get("direction")
        if direction == "gap":
            buffers["rx"].clear()
            yield row
            continue
        if direction not in buffers:
            yield row
            continue
        pending = buffers[direction]
        pending.extend(bytes.fromhex(row.get("hex", "")))
        while len(pending) >= 3:
            offset = pending.find(bytes([0x55, 0x00]))
            if offset < 0:
                yield {"event": "unframed", "direction": direction, "hex": pending.hex()}
                pending[:] = pending[-1:] if pending[-1:] == b"U" else b""
                break
            if offset:
                yield {"event": "unframed", "direction": direction, "hex": pending[:offset].hex()}
                del pending[:offset]
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
            address = frame[4]
            names = {
                0x30: "VX",
                0x31: "VY",
                0x32: "VYAW",
                0x5C: "MOTOR_SPEED",
                0x01: "BATTERY",
                0x07: "FIRMWARE_VERSION",
                0x62: "ROLL",
                0x63: "PITCH",
                0x64: "YAW",
            }
            yield {
                "event": "frame",
                "direction": direction,
                "time_ns": row.get("time_ns"),
                "timestamp": "last_observed_chunk",
                "mode": frame[3],
                "address": address,
                "name": names.get(address, "unknown"),
                "payload_hex": frame[5:-3].hex(),
                "hex": frame.hex(),
                "checksum_valid": True,
            }
        if row.get("truncated"):
            pending.clear()
            yield {"event": "gap", "direction": direction, "cause": "capture_truncated"}
    for direction, pending in buffers.items():
        if pending:
            yield {"event": "partial_frame", "direction": direction, "hex": pending.hex()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="action", required=True)
    subs.add_parser("list")
    for action in ("attach", "detach", "status"):
        cmd = subs.add_parser(action)
        cmd.add_argument("--pid", type=int, required=True)
        if action == "attach":
            cmd.add_argument("--seconds", type=int, default=60)
    cmd = subs.add_parser("decode")
    cmd.add_argument("file", type=Path)
    args = parser.parse_args()
    if args.action == "decode":
        with args.file.open() as stream:
            for row in decode(json.loads(line) for line in stream if line.strip()):
                print(json.dumps(row))
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
