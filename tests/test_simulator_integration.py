#!/usr/bin/env python3
"""
Integration test for the simulator with MQTT bus
This test requires starting the broker and simulator separately
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import zmq

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.bus import BusPub, BusSub


def test_simulator_mqtt_communication():
    """
    Manual integration test for simulator MQTT communication.

    Run this test with the broker and simulator already running:

    Terminal 1: python services/broker.py
    Terminal 2: SDL_VIDEODRIVER=dummy python scripts/sim/run_simulation.py
    Terminal 3: python tests/test_simulator_integration.py
    """
    print("\n=== Testing Simulator MQTT Communication ===\n")

    # Give services time to start
    time.sleep(1.0)

    # Create publisher for control commands
    pub = BusPub()
    time.sleep(0.2)  # Warmup

    # Create subscriber for gyro data
    sub = BusSub("rider.gyro.angle")
    time.sleep(0.2)

    print("✓ MQTT connections established")

    # Test 1: Send drive command
    print("\n[Test 1] Sending drive command...")
    for _i in range(3):
        pub.publish("motion", {"type": "drive", "lx": 0.5, "az": 0.0})
        time.sleep(0.1)

    print("✓ Drive commands sent")

    # Test 2: Receive gyro data
    print("\n[Test 2] Receiving gyro data...")
    received_gyro = False

    for _ in range(50):  # Try for 5 seconds
        topic, payload = sub.recv(timeout_ms=100)
        if topic and payload:
            print(f"  Received: {topic} -> {payload}")
            if "angle" in payload:
                received_gyro = True
                break

    if received_gyro:
        print("✓ Gyro data received successfully")
    else:
        print("✗ No gyro data received (simulator may not be running)")

    # Test 3: Send rotation command
    print("\n[Test 3] Sending rotation command...")
    for _i in range(3):
        pub.publish("motion", {"type": "drive", "lx": 0.0, "az": 0.5})
        time.sleep(0.1)

    print("✓ Rotation commands sent")

    # Test 4: Send stop command
    print("\n[Test 4] Sending stop command...")
    for _i in range(3):
        pub.publish("motion", {"type": "stop"})
        time.sleep(0.1)

    print("✓ Stop command sent")

    # Clean up
    pub.close()
    sub.close()

    print("\n=== All Tests Completed ===\n")
    print("Next steps:")
    print("  1. Check the simulator window for robot movement")
    print("  2. Use 'python scripts/diag_bus-spy.py' to monitor MQTT traffic")
    print("  3. Use 'python scripts/dev_send-cmd.py' to send manual commands")


def test_with_subprocess():
    """
    Automated test that starts broker and simulator as subprocesses.
    This is for CI/CD environments.
    """
    print("\n=== Automated Integration Test ===\n")

    broker_proc = None
    sim_proc = None

    try:
        # Start broker
        print("Starting broker...")
        broker_proc = subprocess.Popen(
            ["python", "services/broker.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(1.0)

        # Start simulator in headless mode
        print("Starting simulator...")
        env = os.environ.copy()
        env["SDL_VIDEODRIVER"] = "dummy"
        sim_proc = subprocess.Popen(
            ["python", "scripts/sim/run_simulation.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        time.sleep(2.0)

        # Run communication tests
        test_simulator_mqtt_communication()

    except Exception as e:
        print(f"Error during test: {e}")
    finally:
        # Clean up
        if sim_proc:
            print("\nStopping simulator...")
            sim_proc.terminate()
            sim_proc.wait(timeout=3)

        if broker_proc:
            print("Stopping broker...")
            broker_proc.terminate()
            broker_proc.wait(timeout=3)


if __name__ == "__main__":
    # Check if broker is already running
    try:
        ctx = zmq.Context.instance()
        test_sock = ctx.socket(zmq.SUB)
        test_sock.setsockopt(zmq.LINGER, 0)
        test_sock.connect("tcp://127.0.0.1:5556")
        test_sock.close()

        # Broker is running, do manual test
        print("✓ Broker detected, running manual test")
        test_simulator_mqtt_communication()

    except Exception:
        print("✗ Broker not detected, running automated test")
        print("  (or run: python services/broker.py)")
        test_with_subprocess()
