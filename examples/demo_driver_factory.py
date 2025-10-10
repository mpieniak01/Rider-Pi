#!/usr/bin/env python3
"""
Example: Using driver factories with simulation mode

This script demonstrates how to use the new driver factory functions
to seamlessly switch between physical hardware and simulation.

Usage:
    # Physical mode (default)
    python3 examples/demo_driver_factory.py

    # Simulation mode
    RIDER_SIMULATOR=1 python3 examples/demo_driver_factory.py
"""

from __future__ import annotations

import logging
import os
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drivers.lcd import PanelCfg, get_lcd_driver
from drivers.xgo import get_robot_driver

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

LOG = logging.getLogger("demo")


def demo_robot_driver():
    """Demonstrate XGO robot driver factory."""
    LOG.info("=" * 60)
    LOG.info("XGO Robot Driver Demo")
    LOG.info("=" * 60)

    mode = "SIMULATION" if os.getenv("RIDER_SIMULATOR") == "1" else "PHYSICAL"
    LOG.info(f"Mode: {mode}")

    # Get driver using factory function
    robot = get_robot_driver()
    LOG.info(f"Driver type: {type(robot).__name__}")
    LOG.info(f"Driver OK: {robot.ok()}")

    # Test basic operations
    LOG.info("\nTesting basic operations:")

    # Stop
    robot.stop()

    # Forward motion
    LOG.info("Moving forward...")
    robot.drive("forward", speed=0.3, dur=0.5)
    time.sleep(0.6)

    # Turn left
    LOG.info("Turning left...")
    robot.spin("left", speed=0.3, dur=0.5)
    time.sleep(0.6)

    # Stop
    LOG.info("Stopping...")
    robot.stop()

    # Check battery
    battery = robot.battery()
    if battery is not None:
        LOG.info(f"Battery level: {battery * 100:.1f}%")

    # Check IMU
    imu = robot.imu()
    if imu:
        LOG.info(f"IMU: roll={imu['roll']:.1f}° pitch={imu['pitch']:.1f}° yaw={imu['yaw']:.1f}°")

    LOG.info("\n✓ Robot driver demo complete")


def demo_lcd_driver():
    """Demonstrate LCD driver factory."""
    LOG.info("\n" + "=" * 60)
    LOG.info("LCD Driver Demo")
    LOG.info("=" * 60)

    mode = "SIMULATION" if os.getenv("RIDER_SIMULATOR") == "1" else "PHYSICAL"
    LOG.info(f"Mode: {mode}")

    # Get driver using factory function
    cfg = PanelCfg(rotate=270, bgr=True)
    lcd = get_lcd_driver(cfg)
    LOG.info(f"Driver type: {type(lcd).__name__}")

    # Try to create a simple image (requires PIL)
    try:
        from PIL import Image, ImageDraw

        LOG.info("\nCreating test pattern...")
        img = Image.new("RGB", (240, 240), color=(0, 0, 128))
        draw = ImageDraw.Draw(img)
        draw.rectangle([20, 20, 220, 220], outline=(255, 255, 0), width=3)
        draw.text((60, 110), "RIDER-PI", fill=(255, 255, 255))

        LOG.info("Displaying image...")
        lcd.ShowImage(img)

        LOG.info("\n✓ LCD driver demo complete")
    except ImportError:
        LOG.warning("PIL not available - skipping image test")


def main():
    """Run all demos."""
    LOG.info("Driver Factory Demo")
    LOG.info("=" * 60)
    LOG.info(f"RIDER_SIMULATOR: {os.getenv('RIDER_SIMULATOR', '0')}")
    LOG.info("")

    try:
        demo_robot_driver()
        demo_lcd_driver()

        LOG.info("\n" + "=" * 60)
        LOG.info("All demos completed successfully!")
        LOG.info("=" * 60)

    except KeyboardInterrupt:
        LOG.info("\nDemo interrupted by user")
    except Exception as e:
        LOG.exception(f"Demo error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
