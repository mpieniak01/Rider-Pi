#!/usr/bin/env python3
"""
Rider-Pi 2D Simulator - Main Entry Point

Run the 2D simulation environment.
"""

from __future__ import annotations

import logging

from sim.world import World

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

LOG = logging.getLogger("run_simulation")


def main():
    """Main simulation loop."""
    # Create world with default map
    world = World(map_file="sim/maps/map01.txt")

    LOG.info("Starting simulation...")
    running = True

    try:
        while running:
            # Handle events
            running = world.handle_events()

            # Render
            world.render()

            # Tick
            world.tick()

    except KeyboardInterrupt:
        LOG.info("Simulation interrupted by user")
    finally:
        world.quit()
        LOG.info("Simulation ended")


if __name__ == "__main__":
    main()
