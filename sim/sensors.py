#!/usr/bin/env python3
"""
Virtual Sensors - Simulated gyroscope and camera with MQTT publishing
"""

from __future__ import annotations

import io
import json
import logging
import math
import os
import time
from time import monotonic

import pygame
import zmq

LOG = logging.getLogger("sim.sensors")

# MQTT configuration
BUS_PUB_ADDR = os.getenv("BUS_PUB_ADDR", "tcp://127.0.0.1:5555")
GYRO_TOPIC = os.getenv("GYRO_TOPIC", "rider.gyro.angle")
CAMERA_TOPIC = os.getenv("CAMERA_TOPIC", "rider.camera.frame")


class VirtualGyro:
    """Virtual gyroscope that publishes robot orientation."""

    def __init__(self, rate_hz: float = 10.0):
        self.rate_hz = float(rate_hz)
        # Zachowujemy 'period' dla testów (kompatybilność API) i wewnętrznie używamy monotonic.
        self.period: float = 1.0 / max(0.1, self.rate_hz)
        self._min_interval: float = self.period
        self.last_pub: float = 0.0  # monotonic timestamp ostatniej realnej publikacji

        self._ctx = None
        self._pub = None
        self._init_mqtt()

    def _init_mqtt(self) -> None:
        """Initialize MQTT publisher."""
        try:
            self._ctx = zmq.Context.instance()
            self._pub = self._ctx.socket(zmq.PUB)
            self._pub.connect(BUS_PUB_ADDR)
            time.sleep(0.1)  # Warmup
            LOG.info("Gyro PUB → %s topic='%s' @ %s Hz", BUS_PUB_ADDR, GYRO_TOPIC, self.rate_hz)
        except Exception as e:  # noqa: BLE001
            LOG.warning("Failed to initialize gyro MQTT: %s", e)

    def publish(self, angle: float) -> None:
        """Publish gyro angle if enough time has passed (rate-limited)."""
        now_mono = monotonic()
        if self._min_interval and (now_mono - self.last_pub) < self._min_interval:
            # Zbyt wcześnie — brak wysyłki i brak zmiany last_pub
            return

        # Aktualizacja znacznika dopiero przy realnej publikacji.
        self.last_pub = now_mono

        if self._pub:
            try:
                # Do payloadu używamy zegara ściennego (przydatny dla logów/zdarzeń).
                now_wall = time.time()
                angle_deg = math.degrees(angle)
                payload = json.dumps({"angle": angle_deg, "ts": now_wall}).encode("utf-8")
                self._pub.send_multipart([GYRO_TOPIC.encode("utf-8"), payload])
            except Exception as e:  # noqa: BLE001
                LOG.debug("Error publishing gyro: %s", e)


class VirtualCamera:
    """Virtual camera that renders first-person view with perspective."""

    def __init__(self, width: int = 320, height: int = 240, fov: float = 60.0, rate_hz: float = 5.0):
        self.width = int(width)
        self.height = int(height)
        self.fov = float(fov)  # Field of view in degrees
        self.rate_hz = float(rate_hz)

        # Zachowujemy 'period' dla zgodności z testami; limitowanie na monotonic.
        self.period: float = 1.0 / max(0.1, self.rate_hz)
        self._min_interval: float = self.period
        self.last_pub: float = 0.0  # monotonic timestamp ostatniej realnej publikacji

        self._ctx = None
        self._pub = None
        self._init_mqtt()

        # Create camera surface
        self.surface = pygame.Surface((self.width, self.height))

    def _init_mqtt(self) -> None:
        """Initialize MQTT publisher."""
        try:
            self._ctx = zmq.Context.instance()
            self._pub = self._ctx.socket(zmq.PUB)
            self._pub.connect(BUS_PUB_ADDR)
            time.sleep(0.1)  # Warmup
            LOG.info("Camera PUB → %s topic='%s' @ %s Hz", BUS_PUB_ADDR, CAMERA_TOPIC, self.rate_hz)
        except Exception as e:  # noqa: BLE001
            LOG.warning("Failed to initialize camera MQTT: %s", e)

    def render(self, robot_x: float, robot_y: float, robot_angle: float, walls: list):
        """
        Render first-person view from robot's perspective.

        Args:
            robot_x, robot_y: Robot position in world coordinates
            robot_angle: Robot orientation in radians
            walls: List of wall segments as ((x1, y1), (x2, y2))
        """
        self.surface.fill((135, 206, 235))  # Sky blue

        # Ground
        ground_height = self.height // 2
        pygame.draw.rect(self.surface, (101, 67, 33), (0, ground_height, self.width, self.height - ground_height))

        # Render walls with perspective
        fov_rad = math.radians(self.fov)

        # Sample rays across the field of view
        num_rays = self.width
        for i in range(num_rays):
            # Calculate ray angle
            ray_angle = robot_angle + (i / num_rays - 0.5) * fov_rad

            # Cast ray and find closest wall
            min_dist = float("inf")
            for wall in walls:
                (x1, y1), (x2, y2) = wall
                dist = self._ray_wall_intersection(robot_x, robot_y, ray_angle, x1, y1, x2, y2)
                if dist and dist < min_dist:
                    min_dist = dist

            # Draw wall column based on distance
            if min_dist < float("inf"):
                # Perspective projection: closer = taller
                min_dist = max(min_dist, 0.1)  # Limit max distance to avoid division by zero
                wall_height = min(self.height, int(self.height / (min_dist * 0.5)))
                wall_top = (self.height - wall_height) // 2

                # Simple shading based on distance
                brightness = max(50, min(200, int(200 / (1 + min_dist * 0.3))))
                color = (brightness // 2, brightness // 2, brightness // 2)

                pygame.draw.line(self.surface, color, (i, wall_top), (i, wall_top + wall_height), 1)

        return self.surface

    def _ray_wall_intersection(
        self, rx: float, ry: float, angle: float, x1: float, y1: float, x2: float, y2: float
    ) -> float | None:
        """
        Calculate intersection distance between a ray and a wall segment.

        Returns distance if intersection exists, None otherwise.
        """
        # Ray direction
        ray_dx = math.cos(angle)
        ray_dy = math.sin(angle)

        # Wall direction
        wall_dx = x2 - x1
        wall_dy = y2 - y1

        # Solve parametric equations
        denominator = ray_dx * wall_dy - ray_dy * wall_dx
        if abs(denominator) < 1e-10:
            return None  # Parallel

        t = ((x1 - rx) * wall_dy - (y1 - ry) * wall_dx) / denominator
        u = ((x1 - rx) * ray_dy - (y1 - ry) * ray_dx) / denominator

        # Check if intersection is valid
        if t >= 0 and 0 <= u <= 1:
            return t
        return None

    def publish(self) -> None:
        """Publish camera frame if enough time has passed (rate-limited)."""
        now_mono = monotonic()
        if self._min_interval and (now_mono - self.last_pub) < self._min_interval:
            # Zbyt wcześnie — brak wysyłki i brak zmiany last_pub
            return

        # Aktualizujemy last_pub dopiero przy realnej publikacji
        self.last_pub = now_mono

        if self._pub:
            try:
                # Convert pygame surface to JPEG bytes
                import pygame.image

                buf = io.BytesIO()
                # Jeśli build pygame nie obsłuży "JPEG", można rozważyć PNG.
                pygame.image.save(self.surface, buf, "JPEG")
                img_bytes = buf.getvalue()

                # Publish as binary data
                self._pub.send_multipart([CAMERA_TOPIC.encode("utf-8"), img_bytes])
            except Exception as e:  # noqa: BLE001
                LOG.debug("Error publishing camera: %s", e)
