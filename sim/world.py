#!/usr/bin/env python3
"""
World - Main simulation environment with Pygame rendering
"""

from __future__ import annotations

import logging
import math
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

    def __init__(self, map_file: str = None, cell_size: int = 40, fps: int = 60):
        # Rider-Pi: kompatybilność z testami — parametry rozdzielczości i FPS
        self.cell_size = int(cell_size)
        self.fps = int(fps)
        # Zachowaj zgodność z kodem używającym globalnego CELL_SIZE
        try:
            global CELL_SIZE
            CELL_SIZE = self.cell_size
        except Exception:
            pass
        # Zegar do regulacji klatek
        self.clock = getattr(self, 'clock', None) or pygame.time.Clock()
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
        """
        Load map from text file.

        Format:
        - 'X' = wall/obstacle
        - 'R' = robot start position
        - 'M' = goal/target
        - ' ' = empty space
        """
        try:
            with open(filename) as f:
                lines = f.readlines()

            # Parse map
            self.map_height = len(lines)
            self.map_width = max(len(line.rstrip("\n")) for line in lines) if lines else 0

            for y, line in enumerate(lines):
                for x, char in enumerate(line.rstrip("\n")):
                    if char == "X":
                        # Add wall
                        self.walls.append((x, y))
                    elif char == "R":
                        self.start_pos = (x, y)
                    elif char == "M":
                        self.goal = (x, y)

            LOG.info(f"Map loaded: {self.map_width}x{self.map_height}, walls={len(self.walls)}")

            # Calculate wall segments for raycasting
            self._build_wall_segments()

        except Exception as e:
            LOG.error(f"Failed to load map {filename}: {e}")
            sys.exit(1)

    def _build_wall_segments(self):
        """Build wall segments from grid cells for raycasting."""
        self.wall_segments = []

        # For each wall cell, create line segments on its edges
        for wx, wy in self.walls:
            # Convert grid to world coordinates (center of cell)
            x = wx
            y = wy

            # Check each direction and add edge if no wall neighbor
            # Top edge
            if (wx, wy - 1) not in self.walls:
                self.wall_segments.append(((x, y), (x + 1, y)))
            # Bottom edge
            if (wx, wy + 1) not in self.walls:
                self.wall_segments.append(((x, y + 1), (x + 1, y + 1)))
            # Left edge
            if (wx - 1, wy) not in self.walls:
                self.wall_segments.append(((x, y), (x, y + 1)))
            # Right edge
            if (wx + 1, wy) not in self.walls:
                self.wall_segments.append(((x + 1, y), (x + 1, y + 1)))

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

    def render_main_panel(self, robot=None):
        """Render the main top-down view panel."""
        self.main_surface.fill((40, 40, 40))  # Dark gray background

        # Draw walls
        for wx, wy in self.walls:
            screen_x, screen_y = self.grid_to_screen(wx, wy)
            pygame.draw.rect(self.main_surface, (100, 100, 100), (screen_x, screen_y, CELL_SIZE, CELL_SIZE))

        # Draw goal
        if self.goal:
            gx, gy = self.goal
            screen_x, screen_y = self.grid_to_screen(gx + 0.5, gy + 0.5)
            pygame.draw.circle(self.main_surface, (0, 255, 0), (screen_x, screen_y), CELL_SIZE // 3)

        # Draw robot
        if robot:
            rx, ry, angle = robot.x, robot.y, robot.angle
            screen_x, screen_y = self.grid_to_screen(rx, ry)

            # Robot body (rectangle)
            robot_size = CELL_SIZE * 0.6
            robot_rect = pygame.Rect(0, 0, robot_size, robot_size * 0.7)
            robot_rect.center = (screen_x, screen_y)

            # Rotate robot
            robot_surf = pygame.Surface((robot_size * 2, robot_size * 2), pygame.SRCALPHA)
            pygame.draw.rect(robot_surf, (0, 150, 255), robot_rect)

            # Direction indicator
            pygame.draw.line(
                robot_surf,
                (255, 255, 0),
                (robot_size, robot_size),
                (robot_size + robot_size * 0.8, robot_size),
                3,
            )

            # Rotate and blit
            rotated = pygame.transform.rotate(robot_surf, -math.degrees(angle))
            rotated_rect = rotated.get_rect(center=(screen_x, screen_y))
            self.main_surface.blit(rotated, rotated_rect)

        # Grid lines (optional, faint)
        for x in range(self.map_width + 1):
            screen_x, screen_y1 = self.grid_to_screen(x, 0)
            _, screen_y2 = self.grid_to_screen(x, self.map_height)
            pygame.draw.line(self.main_surface, (60, 60, 60), (screen_x, screen_y1), (screen_x, screen_y2), 1)

        for y in range(self.map_height + 1):
            screen_x1, screen_y = self.grid_to_screen(0, y)
            screen_x2, _ = self.grid_to_screen(self.map_width, y)
            pygame.draw.line(self.main_surface, (60, 60, 60), (screen_x1, screen_y), (screen_x2, screen_y), 1)

    def render_side_panel(self, robot=None, camera_surface=None):
        """Render the side panel with camera view and telemetry."""
        self.side_surface.fill((30, 30, 30))  # Darker gray

        y_offset = 10

        # Title
        title = self.title_font.render("Rider-Pi Simulator", True, (255, 255, 255))
        self.side_surface.blit(title, (10, y_offset))
        y_offset += 30

        # Divider
        pygame.draw.line(self.side_surface, (100, 100, 100), (10, y_offset), (self.side_panel_width - 10, y_offset), 1)
        y_offset += 15

        # Camera view
        if camera_surface:
            cam_label = self.font.render("First-Person View:", True, (200, 200, 200))
            self.side_surface.blit(cam_label, (10, y_offset))
            y_offset += 20

            # Scale camera surface to fit panel
            cam_width = self.side_panel_width - 20
            cam_height = int(cam_width * camera_surface.get_height() / camera_surface.get_width())
            scaled_cam = pygame.transform.scale(camera_surface, (cam_width, cam_height))
            self.side_surface.blit(scaled_cam, (10, y_offset))
            y_offset += cam_height + 15

        # Telemetry
        if robot:
            state = robot.get_state()

            telem_label = self.font.render("Telemetry:", True, (200, 200, 200))
            self.side_surface.blit(telem_label, (10, y_offset))
            y_offset += 20

            # Display robot state
            telemetry_lines = [
                f"Position: ({state['x']:.2f}, {state['y']:.2f})",
                f"Angle: {math.degrees(state['angle']):.1f}°",
                f"Linear: {state['linear_vel']:.3f} m/s",
                f"Angular: {state['angular_vel']:.3f} rad/s",
            ]

            for line in telemetry_lines:
                text = self.font.render(line, True, (150, 255, 150))
                self.side_surface.blit(text, (15, y_offset))
                y_offset += 18

        # Instructions at bottom
        y_offset = self.height - 80
        pygame.draw.line(self.side_surface, (100, 100, 100), (10, y_offset), (self.side_panel_width - 10, y_offset), 1)
        y_offset += 10

        instructions = ["ESC - Quit", "Control via MQTT:", f"  Topic: {os.getenv('MOTION_TOPIC', 'motion')}"]

        for line in instructions:
            text = self.font.render(line, True, (180, 180, 180))
            self.side_surface.blit(text, (10, y_offset))
            y_offset += 16

    def render(self, robot=None, camera_surface=None):
        """Render the complete simulation window."""
        # Render panels
        self.render_main_panel(robot)
        self.render_side_panel(robot, camera_surface)

        # Blit panels to screen
        self.screen.blit(self.main_surface, (0, 0))
        self.screen.blit(self.side_surface, (self.main_panel_width, 0))

        # Draw divider
        pygame.draw.line(
            self.screen,
            (100, 100, 100),
            (self.main_panel_width, 0),
            (self.main_panel_width, self.height),
            2,
        )

        # Update display
        pygame.display.flip()

    def tick(self) -> float:
        """
        Advance simulation by one frame.

        Returns:
            Delta time in seconds
        """
        return self.clock.tick(self.fps) / 1000.0

    def handle_events(self) -> bool:
        """
        Handle pygame events.

        Returns:
            False if should quit, True otherwise
        """
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return False
        return True

    def quit(self):
        """Clean up and quit pygame."""
        pygame.quit()
