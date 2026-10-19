"""The virtual robot uses an in-process transport, never the production BUS."""

from __future__ import annotations

import json
import time
import uuid

import zmq

from sim import robot as simulation


def test_mqtt_integration(monkeypatch):
    endpoint = "inproc://simulator-test-" + uuid.uuid4().hex
    monkeypatch.setattr(simulation, "BUS_SUB_ADDR", endpoint)
    ctx = zmq.Context.instance()
    pub = ctx.socket(zmq.PUB)
    pub.bind(endpoint)
    robot = simulation.SimulatedRobot(x=5.0, y=5.0, angle=0.0)
    try:
        time.sleep(0.05)  # Allow subscription registration inside this context.
        pub.send_multipart([b"motion", json.dumps({"type": "drive", "lx": 1.0, "az": 0.0}).encode()])
        deadline = time.monotonic() + 1.0
        while robot.linear_vel == 0 and time.monotonic() < deadline:
            robot.recv_commands()
            time.sleep(0.005)
        assert robot.linear_vel > 0
        assert robot.angular_vel == 0
        before = robot.x
        robot.update(1.0)
        assert robot.x > before
        pub.send_multipart([b"motion", b'{"type":"stop"}'])
        deadline = time.monotonic() + 1.0
        while robot.linear_vel != 0 and time.monotonic() < deadline:
            robot.recv_commands()
            time.sleep(0.005)
        assert robot.linear_vel == 0
        assert robot.angular_vel == 0
    finally:
        robot._sub.close(linger=0)
        pub.close(linger=0)
