#!/usr/bin/env python3
"""
World - Main simulation environment with Pygame rendering
"""

from __future__ import annotations

import logging
import os
import pygame

LOG = logging.getLogger("sim.world")

# Colors
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GRAY = (128, 128, 128)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
YELLOW = (255, 255, 0)


class World:
    """
    2D world with map, robot rendering, and telemetry display.
    """

    def __init__(self, map_file: str, cell_size: int = 40, fps: int = 60):
        """
        Initialize the world.

        Args:
            map_file: Path to map text file
            cell_size: Size of each cell in pixels
            fps: Target frames per second
        """
        self.cell_size = cell_size
        self.fps = fps
        self.map_data = []
        self.start_pos: tuple[int, int] | None = None
        self.wall_segments = []

        # Load map
        self._load_map(map_file)

        # Calculate window size
        self.map_height = len(self.map_data)
        self.map_width = max(len(row) for row in self.map_data) if self.map_data else 0
        self.panel_width = 250
        self.window_width = self.map_width * cell_size + self.panel_width
        self.window_height = self.map_height * cell_size

        # Initialize Pygame
        pygame.init()
        self.screen = pygame.display.set_mode((self.window_width, self.window_height))
        pygame.display.set_caption("Rider-Pi 2D Simulator")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 24)
        self.small_font = pygame.font.Font(None, 18)

        LOG.info(f"World initialized: {self.map_width}x{self.map_height} cells")

    def _load_map(self, map_file: str):
        """Load map from text file."""
        if not os.path.exists(map_file):
            LOG.error(f"Map file not found: {map_file}")
            self.map_data = [["#" for _ in range(10)] for _ in range(10)]
            return

        try:
            with open(map_file) as f:
                lines = f.readlines()
                self.map_data = [list(line.rstrip("\n")) for line in lines]

            # Find robot start position 'R' and wall segments
            for y, row in enumerate(self.map_data):
                for x, cell in enumerate(row):
                    if cell == "R":
                        self.start_pos = (x, y)
                        LOG.info(f"Robot start position: ({x}, {y})")
                    elif cell == "#":
                        # Add wall segment for collision/sensor detection
                        self.wall_segments.append((x, y))

            LOG.info(f"Loaded map from {map_file}: {len(self.wall_segments)} walls")
        except Exception as e:
            LOG.error(f"Failed to load map: {e}")
            self.map_data = []

    def handle_events(self) -> bool:
        """
        Handle Pygame events.

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

    def tick(self) -> float:
        """
        Tick the clock and return delta time.

        Returns:
            Delta time in seconds
        """
        dt_ms = self.clock.tick(self.fps)
        return dt_ms / 1000.0

    def render(self, robot, camera_surface=None):
        """
        Render the world, robot, and telemetry.

        Args:
            robot: SimulatedRobot instance
            camera_surface: Optional camera view surface
        """
        self.screen.fill(BLACK)

        # Draw map
        for y, row in enumerate(self.map_data):
            for x, cell in enumerate(row):
                px = x * self.cell_size
                py = y * self.cell_size

                if cell == "#":
                    # Wall
                    pygame.draw.rect(self.screen, GRAY, (px, py, self.cell_size, self.cell_size))
                elif cell == " " or cell == ".":
                    # Floor
                    pygame.draw.rect(self.screen, WHITE, (px, py, self.cell_size, self.cell_size), 1)

        # Draw robot
        self._draw_robot(robot)

        # Draw telemetry panel
        self._draw_telemetry(robot, camera_surface)

        pygame.display.flip()

    def _draw_robot(self, robot):
        """Draw the robot on the map."""
        # Convert world coordinates to screen coordinates
        screen_x = robot.x * self.cell_size
        screen_y = robot.y * self.cell_size

        # Robot body (rectangle)
        robot_width = self.cell_size * 0.6
        robot_height = self.cell_size * 0.4

        # Create robot rectangle
        robot_rect = pygame.Surface((robot_width, robot_height), pygame.SRCALPHA)
        pygame.draw.rect(robot_rect, (*BLUE, 200), (0, 0, robot_width, robot_height))

        # Draw direction indicator (front of robot)
        pygame.draw.circle(robot_rect, RED, (int(robot_width * 0.85), int(robot_height / 2)), 3)

        # Rotate robot
        rotated = pygame.transform.rotate(robot_rect, -robot.angle * 180 / 3.14159)

        # Get rect and center it on robot position
        rect = rotated.get_rect(center=(screen_x, screen_y))

        # Draw
        self.screen.blit(rotated, rect)

    def _draw_telemetry(self, robot, camera_surface):
        """Draw telemetry panel on the right side."""
        panel_x = self.map_width * self.cell_size
        panel_width = self.panel_width

        # Panel background
        pygame.draw.rect(self.screen, (40, 40, 40), (panel_x, 0, panel_width, self.window_height))

        y_offset = 20

        # Title
        title = self.font.render("Telemetry", True, WHITE)
        self.screen.blit(title, (panel_x + 10, y_offset))
        y_offset += 40

        # Robot state
        state = robot.get_state()

        # Position
        text = self.small_font.render(f"X: {state['x']:.2f} m", True, GREEN)
        self.screen.blit(text, (panel_x + 10, y_offset))
        y_offset += 25

        text = self.small_font.render(f"Y: {state['y']:.2f} m", True, GREEN)
        self.screen.blit(text, (panel_x + 10, y_offset))
        y_offset += 25

        # Angle (convert to degrees)
        angle_deg = state['angle'] * 180 / 3.14159
        text = self.small_font.render(f"Angle: {angle_deg:.1f}°", True, GREEN)
        self.screen.blit(text, (panel_x + 10, y_offset))
        y_offset += 35

        # Velocities
        text = self.small_font.render(f"Lin: {state['linear_vel']:.2f} m/s", True, YELLOW)
        self.screen.blit(text, (panel_x + 10, y_offset))
        y_offset += 25

        text = self.small_font.render(f"Ang: {state['angular_vel']:.2f} rad/s", True, YELLOW)
        self.screen.blit(text, (panel_x + 10, y_offset))
        y_offset += 35

        # Camera view
        if camera_surface:
            y_offset += 10
            cam_text = self.small_font.render("Camera View:", True, WHITE)
            self.screen.blit(cam_text, (panel_x + 10, y_offset))
            y_offset += 25
            # Scale camera surface to fit panel
            cam_w, cam_h = camera_surface.get_size()
            scale = min((panel_width - 20) / cam_w, 120 / cam_h)
            scaled_w = int(cam_w * scale)
            scaled_h = int(cam_h * scale)
            scaled_surface = pygame.transform.scale(camera_surface, (scaled_w, scaled_h))
            self.screen.blit(scaled_surface, (panel_x + 10, y_offset))

    def quit(self):
        """Clean up and quit Pygame."""
=======
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
