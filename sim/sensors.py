#!/usr/bin/env python3
"""
Virtual Sensors - Simulated sensor implementations with MQTT publishing
"""

from __future__ import annotations

import json
import logging
import math
import os
import time

import pygame
import zmq

LOG = logging.getLogger("sim.sensors")

# Sensor configuration
STATE_PUB_ADDR = os.getenv("BUS_PUB_ADDR", "tcp://127.0.0.1:5555")
GYRO_TOPIC = os.getenv("GYRO_TOPIC", "sensor.gyro")
CAMERA_TOPIC = os.getenv("CAMERA_TOPIC", "sensor.camera")


class VirtualGyro:
    """
    Virtual gyroscope that publishes orientation data.
    """

    def __init__(self, rate_hz: float = 10.0):
        self.rate_hz = rate_hz
        self.last_pub = 0.0

        # MQTT setup
        self._ctx = None
        self._pub = None
        self._init_mqtt()

    def _init_mqtt(self):
        """Initialize MQTT publisher."""
        try:
            self._ctx = zmq.Context.instance()
            self._pub = self._ctx.socket(zmq.PUB)
            self._pub.connect(STATE_PUB_ADDR)
            LOG.info(f"Gyro PUB connected to {STATE_PUB_ADDR} topic='{GYRO_TOPIC}'")
        except Exception as e:
            LOG.warning(f"Failed to initialize gyro MQTT: {e}")

    def publish(self, angle: float):
        """
        Publish gyro data.

        Args:
            angle: Current angle in radians
        """
        if not self._pub:
            return

        now = time.time()
        if now - self.last_pub < 1.0 / self.rate_hz:
            return

        self.last_pub = now

        try:
            data = {
                "ts": now,
                "yaw": math.degrees(angle),
                "roll": 0.0,
                "pitch": 0.0,
            }
            msg = json.dumps(data, separators=(",", ":"))
            self._pub.send_string(f"{GYRO_TOPIC} {msg}")
            LOG.debug(f"Gyro: yaw={data['yaw']:.1f}°")
        except Exception as e:
            LOG.debug(f"Error publishing gyro: {e}")


class VirtualCamera:
    """
    Virtual camera that renders a first-person view and publishes frames.
    """

    def __init__(self, width: int = 320, height: int = 240, fov: float = 60.0, rate_hz: float = 5.0):
        self.width = width
        self.height = height
        self.fov = fov  # Field of view in degrees
        self.rate_hz = rate_hz
        self.last_pub = 0.0

        # Create surface for rendering
        self.surface = pygame.Surface((width, height))

        # MQTT setup
        self._ctx = None
        self._pub = None
        self._init_mqtt()

    def _init_mqtt(self):
        """Initialize MQTT publisher."""
        try:
            self._ctx = zmq.Context.instance()
            self._pub = self._ctx.socket(zmq.PUB)
            self._pub.connect(STATE_PUB_ADDR)
            LOG.info(f"Camera PUB connected to {STATE_PUB_ADDR} topic='{CAMERA_TOPIC}'")
        except Exception as e:
            LOG.warning(f"Failed to initialize camera MQTT: {e}")

    def render(self, robot_x: float, robot_y: float, robot_angle: float, wall_segments: list) -> pygame.Surface:
        """
        Render first-person camera view.

        Args:
            robot_x: Robot X position
            robot_y: Robot Y position
            robot_angle: Robot angle in radians
            wall_segments: List of wall positions [(x, y), ...]

        Returns:
            Rendered surface
        """
        # Simple raycasting-style rendering
        self.surface.fill((50, 50, 100))  # Sky color

        # Draw ground
        pygame.draw.rect(self.surface, (100, 80, 60), (0, self.height // 2, self.width, self.height // 2))

        # Cast rays and draw walls
        half_fov = math.radians(self.fov / 2)
        num_rays = self.width // 2  # Lower resolution for performance

        for i in range(num_rays):
            # Calculate ray angle
            ray_angle = robot_angle - half_fov + (i / num_rays) * (2 * half_fov)

            # Cast ray to find nearest wall
            min_dist = float('inf')
            for wx, wy in wall_segments:
                # Distance to wall center
                dx = (wx + 0.5) - robot_x
                dy = (wy + 0.5) - robot_y
                dist = math.sqrt(dx * dx + dy * dy)

                # Check if wall is in ray direction (simplified)
                wall_angle = math.atan2(dy, dx)
                angle_diff = abs(wall_angle - ray_angle)
                if angle_diff > math.pi:
                    angle_diff = 2 * math.pi - angle_diff

                if angle_diff < 0.5 and dist < min_dist:
                    min_dist = dist

            # Draw wall slice
            if min_dist < 20:  # Max view distance
                # Calculate wall height based on distance
                wall_height = int(self.height / max(min_dist, 0.5))
                wall_height = min(wall_height, self.height)

                # Brightness based on distance
                brightness = max(0, 255 - int(min_dist * 20))
                color = (brightness, brightness, brightness)

                # Draw vertical line
                x = i * 2
                y_start = (self.height - wall_height) // 2
                pygame.draw.rect(self.surface, color, (x, y_start, 2, wall_height))

        return self.surface

    def publish(self):
        """Publish camera frame (placeholder for now)."""
        if not self._pub:
            return

        now = time.time()
        if now - self.last_pub < 1.0 / self.rate_hz:
            return

        self.last_pub = now

        try:
            data = {
                "ts": now,
                "width": self.width,
                "height": self.height,
                "format": "placeholder",
            }
            msg = json.dumps(data, separators=(",", ":"))
            self._pub.send_string(f"{CAMERA_TOPIC} {msg}")
            LOG.debug("Camera frame published")
        except Exception as e:
            LOG.debug(f"Error publishing camera: {e}")
