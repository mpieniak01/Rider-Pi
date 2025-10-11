#!/usr/bin/env python3
"""
Example: Using the simulator with a simple navigation algorithm

This demonstrates how to control the simulated robot via MQTT.
The same code works with both the simulator and the real robot.
"""

from __future__ import annotations

import time

from common.bus import BusPub, BusSub


def simple_navigation_demo():
    """Simple navigation: move forward, turn, move forward."""

    print("=== Simple Navigation Demo ===\n")
    print("This script controls the robot (simulator or real)")
    print("Make sure the broker and simulator are running:\n")
    print("  Terminal 1: python services/broker.py")
    print("  Terminal 2: python scripts/sim/run_simulation.py\n")

    # Create publisher for control commands
    pub = BusPub(warmup_ms=300)

    # Create subscriber for gyro data
    sub = BusSub("rider.gyro.angle")

    print("[1/4] Moving forward for 2 seconds...")
    start = time.time()
    while time.time() - start < 2.0:
        pub.publish("motion", {"type": "drive", "lx": 0.3, "az": 0.0})
        time.sleep(0.1)

    print("[2/4] Rotating for 1.5 seconds...")
    start = time.time()
    while time.time() - start < 1.5:
        pub.publish("motion", {"type": "drive", "lx": 0.0, "az": 0.4})
        time.sleep(0.1)

    print("[3/4] Moving forward again for 2 seconds...")
    start = time.time()
    while time.time() - start < 2.0:
        pub.publish("motion", {"type": "drive", "lx": 0.3, "az": 0.0})
        time.sleep(0.1)

    print("[4/4] Stopping...")
    for _ in range(3):
        pub.publish("motion", {"type": "stop"})
        time.sleep(0.1)

    print("\n=== Reading final orientation from gyro ===")
    # Read one gyro message
    topic, payload = sub.recv(timeout_ms=2000)
    if topic and payload:
        print(f"Final angle: {payload.get('angle', 'N/A')}°")
    else:
        print("No gyro data received (is simulator running?)")

    pub.close()
    sub.close()

    print("\n=== Demo Complete ===")


if __name__ == "__main__":
    try:
        simple_navigation_demo()
    except KeyboardInterrupt:
        print("\nDemo interrupted by user")
    except Exception as e:
        print(f"\nError: {e}")
        print("\nMake sure broker and simulator are running!")
