#!/usr/bin/env python3
"""
Demo script to test the navigation WebSocket bridge with simulated data.

This script:
1. Starts the navigation WebSocket bridge
2. Publishes simulated odometry and map data to the bus
3. Shows how the data flows through the system

Usage:
    python3 scripts/demo_navigation_websocket.py
"""

from __future__ import annotations

import math
import time

from common.bus import (
    TOPIC_MAPPER_MAP_DATA,
    TOPIC_ROBOT_POSE,
    BusPub,
)


def generate_circular_path(t: float, radius: float = 2.0, speed: float = 0.3) -> tuple[float, float, float]:
    """Generate a circular path for the robot"""
    angle = speed * t
    x = radius * math.cos(angle)
    y = radius * math.sin(angle)
    theta = angle + math.pi / 2  # Robot faces tangent to circle
    return x, y, theta


def generate_simple_map(width: int = 50, height: int = 50) -> dict:
    """Generate a simple map with some obstacles"""
    # Create an empty map (all unknown)
    grid = [[127 for _ in range(width)] for _ in range(height)]

    # Add some free space in the center
    for y in range(height // 4, 3 * height // 4):
        for x in range(width // 4, 3 * width // 4):
            grid[y][x] = 0  # Free

    # Add some obstacles
    # Horizontal wall
    for x in range(width // 4, width // 2):
        grid[height // 2][x] = 255  # Occupied

    # Vertical wall
    for y in range(height // 4, height // 2):
        grid[y][width // 2] = 255  # Occupied

    return {
        "grid": grid,
        "width_cells": width,
        "height_cells": height,
        "resolution_m": 0.1,
        "origin_x": width * 0.1 / 2,  # Center of map
        "origin_y": height * 0.1 / 2,
        "width_m": width * 0.1,
        "height_m": height * 0.1,
        "ts": time.time(),
    }


def main():
    print("=" * 60)
    print("Navigation WebSocket Bridge Demo")
    print("=" * 60)
    print()
    print("This demo publishes simulated navigation data to the bus.")
    print("The WebSocket bridge should receive and transform this data.")
    print()
    print("To test the full system:")
    print("1. Start the broker: make broker")
    print("2. Start the API server: make api")
    print("3. Open http://localhost:8080/navigation in your browser")
    print("4. Run this demo script in another terminal")
    print()
    print("Press Ctrl+C to stop")
    print("=" * 60)
    print()

    # Create publisher
    pub = BusPub()
    print("✓ Connected to bus")

    # Publish initial map
    print("Publishing initial map...")
    initial_map = generate_simple_map()
    pub.publish(TOPIC_MAPPER_MAP_DATA, initial_map, add_ts=True)
    print(
        f"✓ Published map: {initial_map['width_cells']}x{initial_map['height_cells']} cells, "
        f"{initial_map['resolution_m']}m resolution"
    )
    print()

    # Publish odometry updates in a loop
    print("Publishing odometry updates (robot moving in a circle)...")
    start_time = time.time()
    update_count = 0

    try:
        while True:
            elapsed = time.time() - start_time

            # Generate robot position
            x, y, theta = generate_circular_path(elapsed)

            # Publish pose
            pose = {"x": x, "y": y, "theta": theta, "theta_deg": math.degrees(theta), "ts": time.time()}

            pub.publish(TOPIC_ROBOT_POSE, pose, add_ts=True)

            update_count += 1
            if update_count % 10 == 0:
                print(f"  {update_count} updates | Position: x={x:.2f}m, y={y:.2f}m, θ={math.degrees(theta):.1f}°")

            # Update map occasionally (simulate new obstacle detection)
            if update_count % 50 == 0:
                print("  📍 Publishing updated map...")
                updated_map = generate_simple_map()
                pub.publish(TOPIC_MAPPER_MAP_DATA, updated_map, add_ts=True)

            time.sleep(0.1)  # 10 Hz update rate

    except KeyboardInterrupt:
        print()
        print("=" * 60)
        print(f"Demo stopped. Published {update_count} odometry updates.")
        print("=" * 60)
    finally:
        pub.close()


if __name__ == "__main__":
    main()
