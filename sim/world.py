#!/usr/bin/env python3
"""
World - Main simulation environment with Pygame rendering
"""

from __future__ import annotations

import logging
import os
import sys

import pygame

LOG = logging.getLogger("sim.world")

# Window configuration
WINDOW_WIDTH = int(os.getenv("SIM_WIDTH", "1280"))
WINDOW_HEIGHT = int(os.getenv("SIM_HEIGHT", "720"))
SIDE_PANEL_WIDTH_RATIO = 0.3
FPS = int(os.getenv("SIM_FPS", "30"))

# World configuration
CELL_SIZE = 30  # pixels per grid cell


class World:
    """Main simulation world managing the Pygame window and rendering."""

    def __init__(self, map_file: str = None):
        pygame.init()
        pygame.display.set_caption("Rider-Pi 2D Simulator")

        # Create window
        self.width = WINDOW_WIDTH
        self.height = WINDOW_HEIGHT
        self.screen = pygame.display.set_mode((self.width, self.height))
        self.clock = pygame.time.Clock()

        # Calculate panel dimensions
        self.main_panel_width = int(self.width * (1 - SIDE_PANEL_WIDTH_RATIO))
        self.side_panel_width = self.width - self.main_panel_width

        # Create surfaces for panels
        self.main_surface = pygame.Surface((self.main_panel_width, self.height))
        self.side_surface = pygame.Surface((self.side_panel_width, self.height))

        # Font for telemetry
        pygame.font.init()
        self.font = pygame.font.SysFont("monospace", 14)
        self.title_font = pygame.font.SysFont("monospace", 16, bold=True)

        # Map data
        self.walls = []
        self.goal = None
        self.start_pos = None
        self.map_width = 0
        self.map_height = 0

        if map_file:
            self.load_map(map_file)

        LOG.info(f"World initialized: {self.width}x{self.height}, FPS={FPS}")

    def load_map(self, filename: str):
        """Load map from text file.

        Map format:
        - 'X' = wall
        - 'R' = robot start position
        - 'M' = goal/meta
        - ' ' = empty space
        """
        try:
            with open(filename) as f:
                lines = f.readlines()

            # Parse map
            self.map_height = len(lines)
            self.map_width = max(len(line.rstrip()) for line in lines) if lines else 0

            for y, line in enumerate(lines):
                for x, char in enumerate(line.rstrip()):
                    if char == "X":
                        self.walls.append((x, y))
                    elif char == "R":
                        self.start_pos = (x, y)
                    elif char == "M":
                        self.goal = (x, y)

            LOG.info(f"Map loaded: {self.map_width}x{self.map_height}, walls={len(self.walls)}")

        except Exception as e:
            LOG.error(f"Failed to load map {filename}: {e}")
            sys.exit(1)

    def grid_to_screen(self, x: float, y: float) -> tuple[int, int]:
        """Convert grid coordinates to screen coordinates."""
        # Center the map in the main panel
        map_pixel_width = self.map_width * CELL_SIZE
        map_pixel_height = self.map_height * CELL_SIZE

        offset_x = (self.main_panel_width - map_pixel_width) // 2
        offset_y = (self.height - map_pixel_height) // 2

        screen_x = int(x * CELL_SIZE + offset_x)
        screen_y = int(y * CELL_SIZE + offset_y)

        return screen_x, screen_y

    def render_main_panel(self):
        """Render the main top-down view panel."""
        self.main_surface.fill((50, 50, 50))  # Dark gray background

        # Draw walls
        for wx, wy in self.walls:
            screen_x, screen_y = self.grid_to_screen(wx, wy)
            pygame.draw.rect(self.main_surface, (100, 100, 100), (screen_x, screen_y, CELL_SIZE, CELL_SIZE))

        # Draw goal
        if self.goal:
            gx, gy = self.goal
            screen_x, screen_y = self.grid_to_screen(gx, gy)
            pygame.draw.rect(self.main_surface, (0, 255, 0), (screen_x, screen_y, CELL_SIZE, CELL_SIZE))

        # Draw start position marker
        if self.start_pos:
            sx, sy = self.start_pos
            screen_x, screen_y = self.grid_to_screen(sx, sy)
            pygame.draw.rect(self.main_surface, (0, 0, 255), (screen_x, screen_y, CELL_SIZE, CELL_SIZE))

    def render_side_panel(self):
        """Render the side panel."""
        self.side_surface.fill((30, 30, 30))  # Darker gray

        y_offset = 10

        # Title
        title = self.title_font.render("Rider-Pi Simulator", True, (255, 255, 255))
        self.side_surface.blit(title, (10, y_offset))
        y_offset += 30

        # Divider
        pygame.draw.line(
            self.side_surface,
            (100, 100, 100),
            (10, y_offset),
            (self.side_panel_width - 10, y_offset),
            1,
        )
        y_offset += 15

        # Map info
        if self.map_width > 0:
            info_lines = [
                f"Map Size: {self.map_width}x{self.map_height}",
                f"Walls: {len(self.walls)}",
                f"Start: {self.start_pos}",
                f"Goal: {self.goal}",
            ]

            for line in info_lines:
                text = self.font.render(line, True, (200, 200, 200))
                self.side_surface.blit(text, (10, y_offset))
                y_offset += 18

    def render(self):
        """Render the complete simulation window."""
        # Render panels
        self.render_main_panel()
        self.render_side_panel()

        # Blit panels to screen
        self.screen.blit(self.main_surface, (0, 0))
        self.screen.blit(self.side_surface, (self.main_panel_width, 0))

        # Draw divider between panels
        pygame.draw.line(
            self.screen,
            (100, 100, 100),
            (self.main_panel_width, 0),
            (self.main_panel_width, self.height),
            2,
        )

        pygame.display.flip()

    def tick(self) -> float:
        """Advance the simulation clock and return delta time."""
        return self.clock.tick(FPS) / 1000.0

    def handle_events(self) -> bool:
        """Handle Pygame events. Returns False if quit event detected."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return False
        return True

    def quit(self):
        """Clean up and quit pygame."""
        pygame.quit()
