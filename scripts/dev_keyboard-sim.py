#!/usr/bin/env python3
"""
Simple keyboard control for the simulator using ZMQ bus.

Controls:
  W - Move forward
  S - Move backward
  A - Turn left
  D - Turn right
  Space - Stop
  Q/ESC - Quit

Environment variables:
  BUS_PUB_ADDR - ZMQ publisher address (default: tcp://127.0.0.1:5555)
  MOTION_TOPIC - Motion control topic (default: motion)
"""

from __future__ import annotations

import json
import os
import sys
import termios
import tty

import zmq

# Configuration
BUS_PUB_ADDR = os.getenv("BUS_PUB_ADDR", "tcp://127.0.0.1:5555")
MOTION_TOPIC = os.getenv("MOTION_TOPIC", "motion")


def getch():
    """Get a single character from stdin."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(sys.stdin.fileno())
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch


def main():
    # Setup ZMQ publisher
    ctx = zmq.Context.instance()
    pub = ctx.socket(zmq.PUB)
    pub.connect(BUS_PUB_ADDR)

    print(f"Connected to {BUS_PUB_ADDR}")
    print("Keyboard control for simulator:")
    print("  W - Forward")
    print("  S - Backward")
    print("  A - Turn left")
    print("  D - Turn right")
    print("  Space - Stop")
    print("  Q/ESC - Quit")
    print()

    def send_cmd(cmd: dict):
        """Send command to motion topic."""
        msg = json.dumps(cmd, separators=(",", ":"))
        pub.send_multipart([MOTION_TOPIC.encode("utf-8"), msg.encode("utf-8")])
        print(f"Sent: {cmd}")

    try:
        while True:
            ch = getch()

            if ch in ("q", "Q", "\x1b"):  # q, Q, or ESC
                send_cmd({"type": "stop"})
                print("Quit")
                break
            elif ch in ("w", "W"):
                send_cmd({"type": "drive", "lx": 1.0, "az": 0.0})
            elif ch in ("s", "S"):
                send_cmd({"type": "drive", "lx": -1.0, "az": 0.0})
            elif ch in ("a", "A"):
                send_cmd({"type": "drive", "lx": 0.0, "az": -1.0})
            elif ch in ("d", "D"):
                send_cmd({"type": "drive", "lx": 0.0, "az": 1.0})
            elif ch == " ":
                send_cmd({"type": "stop"})

    except KeyboardInterrupt:
        print("\nInterrupted")
    finally:
        send_cmd({"type": "stop"})


if __name__ == "__main__":
    main()
