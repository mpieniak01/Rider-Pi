#!/usr/bin/env python3
"""
Integration test for simulator with MQTT control.

This test verifies:
1. Broker starts and proxies messages
2. Simulator receives commands via ZMQ
3. Robot responds to drive/stop commands
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import zmq

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sim.robot import SimulatedRobot

# Configuration
BUS_PUB_ADDR = "tcp://127.0.0.1:5555"
BUS_SUB_ADDR = "tcp://127.0.0.1:5556"
MOTION_TOPIC = "motion"


def test_mqtt_integration():
    """Test MQTT integration with robot."""
    print("Starting MQTT integration test...")

    # Start broker as subprocess
    print("Starting ZMQ broker...")
    broker_proc = subprocess.Popen(
        [sys.executable, "services/broker.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for broker to start
    time.sleep(1.0)

    try:
        # Create robot
        print("Creating simulated robot...")
        robot = SimulatedRobot(x=5.0, y=5.0, angle=0.0)

        # Setup publisher
        ctx = zmq.Context.instance()
        pub = ctx.socket(zmq.PUB)
        pub.connect(BUS_PUB_ADDR)

        # Wait for connection
        time.sleep(0.5)

        print("Sending drive command...")
        # Send drive command
        cmd = {"type": "drive", "lx": 1.0, "az": 0.0}
        msg = json.dumps(cmd, separators=(",", ":"))
        pub.send_multipart([MOTION_TOPIC.encode("utf-8"), msg.encode("utf-8")])

        # Wait for message to propagate and subscription to settle
        deadline = time.time() + 2.0
        while time.time() < deadline and robot.linear_vel <= 0.0:
            robot.recv_commands()
            if robot.linear_vel > 0.0:
                break
            time.sleep(0.05)

        # Verify robot received command
        assert robot.linear_vel > 0.0, "Robot should have positive linear velocity"
        assert robot.angular_vel == 0.0, "Robot should have zero angular velocity"
        print(f"✓ Drive command received: lx={robot.linear_vel:.2f}, az={robot.angular_vel:.2f}")

        # Send stop command
        print("Sending stop command...")
        cmd = {"type": "stop"}
        msg = json.dumps(cmd, separators=(",", ":"))
        pub.send_multipart([MOTION_TOPIC.encode("utf-8"), msg.encode("utf-8")])

        deadline = time.time() + 2.0
        while time.time() < deadline and robot.linear_vel != 0.0:
            robot.recv_commands()
            if robot.linear_vel == 0.0:
                break
            time.sleep(0.05)

        # Verify robot stopped
        assert robot.linear_vel == 0.0, "Robot should have zero linear velocity"
        assert robot.angular_vel == 0.0, "Robot should have zero angular velocity"
        print(f"✓ Stop command received: lx={robot.linear_vel:.2f}, az={robot.angular_vel:.2f}")

        # Test physics update
        print("Testing physics simulation...")
        robot.linear_vel = 1.0
        initial_x = robot.x
        robot.update(1.0)
        assert robot.x > initial_x, "Robot should have moved in X direction"
        print(f"✓ Physics simulation works: moved from x={initial_x:.2f} to x={robot.x:.2f}")

        print("\n✓ All MQTT integration tests passed!")

    finally:
        # Cleanup
        print("\nCleaning up...")
        broker_proc.terminate()
        try:
            broker_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            broker_proc.kill()
            broker_proc.wait()


if __name__ == "__main__":
    test_mqtt_integration()
