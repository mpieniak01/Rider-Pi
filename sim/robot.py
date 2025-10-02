#!/usr/bin/env python3
"""
Simulated Robot - Virtual robot model with MQTT control integration
"""

from __future__ import annotations

import json
import logging
import math
import os

import zmq

LOG = logging.getLogger("sim.robot")

# MQTT configuration
BUS_SUB_ADDR = os.getenv("BUS_SUB_ADDR", "tcp://127.0.0.1:5556")
CONTROL_TOPIC = os.getenv("MOTION_TOPIC", "motion")


class SimulatedRobot:
    """
    Virtual robot that receives control commands via MQTT and simulates physics.
    """

    def __init__(self, x: float = 0.0, y: float = 0.0, angle: float = 0.0):
        self.x = x
        self.y = y
        self.angle = angle  # radians
        self.linear_vel = 0.0  # m/s
        self.angular_vel = 0.0  # rad/s

        # MQTT setup
        self._ctx = None
        self._sub = None
        self._poller = None
        self._init_mqtt()

    def _init_mqtt(self):
        """Initialize MQTT subscriber for control commands."""
        try:
            self._ctx = zmq.Context.instance()
            self._sub = self._ctx.socket(zmq.SUB)
            self._sub.connect(BUS_SUB_ADDR)
            self._sub.setsockopt(zmq.SUBSCRIBE, CONTROL_TOPIC.encode("utf-8"))
            self._poller = zmq.Poller()
            self._poller.register(self._sub, zmq.POLLIN)
            LOG.info(f"Robot SUB connected to {BUS_SUB_ADDR} topic='{CONTROL_TOPIC}'")
        except Exception as e:
            LOG.warning(f"Failed to initialize MQTT: {e}")

    def recv_commands(self):
        """Receive and process control commands from MQTT."""
        if not self._sub or not self._poller:
            return

        try:
            socks = dict(self._poller.poll(timeout=0))
            if self._sub in socks and socks[self._sub] == zmq.POLLIN:
                raw = self._sub.recv_multipart()
                payload_bytes = raw[1] if len(raw) >= 2 else raw[-1]
                payload = payload_bytes.decode("utf-8", errors="replace").strip()
                try:
                    cmd = json.loads(payload)
                    self._handle_command(cmd)
                except json.JSONDecodeError:
                    LOG.warning(f"Invalid JSON: {payload[:100]}")
        except Exception as e:
            LOG.debug(f"Error receiving commands: {e}")

    def _handle_command(self, cmd: dict):
        """Process a control command."""
        cmd_type = str(cmd.get("type", "")).lower()
        if cmd_type == "drive":
            lx = float(cmd.get("lx", 0.0))
            az = float(cmd.get("az", 0.0))
            # Scale velocities for simulation (typical robot speed ~0.3 m/s)
            self.linear_vel = lx * 0.3
            self.angular_vel = az * 1.5  # rad/s
            LOG.debug(f"CMD drive: lx={lx:.3f} az={az:.3f}")
        elif cmd_type == "stop":
            self.linear_vel = 0.0
            self.angular_vel = 0.0
            LOG.debug("CMD stop")

    def update(self, delta_time: float):
        """
        Update robot physics based on velocities and delta time.

        Args:
            delta_time: Time step in seconds
        """
        # Update orientation
        self.angle += self.angular_vel * delta_time

        # Normalize angle to [-pi, pi]
        self.angle = math.atan2(math.sin(self.angle), math.cos(self.angle))

        # Update position based on orientation
        self.x += self.linear_vel * math.cos(self.angle) * delta_time
        self.y += self.linear_vel * math.sin(self.angle) * delta_time

    def get_state(self) -> dict:
        """Get current robot state."""
        return {
            "x": self.x,
            "y": self.y,
            "angle": self.angle,
            "linear_vel": self.linear_vel,
            "angular_vel": self.angular_vel,
        }
