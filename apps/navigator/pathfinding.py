#!/usr/bin/env python3
"""
Pathfinding module for navigator - A* algorithm on occupancy grid
"""

from __future__ import annotations

import heapq
import math

# Occupancy grid cell values (must match mapper.py)
CELL_UNKNOWN = 127
CELL_FREE = 0
CELL_OCCUPIED = 255


class Node:
    """A* search node"""

    def __init__(self, x: int, y: int, g: float = 0.0, h: float = 0.0, parent=None):
        self.x = x
        self.y = y
        self.g = g  # Cost from start
        self.h = h  # Heuristic cost to goal
        self.f = g + h  # Total cost
        self.parent = parent

    def __lt__(self, other):
        return self.f < other.f

    def __eq__(self, other):
        return self.x == other.x and self.y == other.y

    def __hash__(self):
        return hash((self.x, self.y))


def heuristic(x1: int, y1: int, x2: int, y2: int) -> float:
    """Euclidean distance heuristic"""
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def world_to_grid(
    x: float, y: float, resolution_m: float, origin_x: float, origin_y: float
) -> tuple[int, int]:
    """
    Convert world coordinates (meters) to grid coordinates (cells).

    Args:
        x: X coordinate in world frame (meters)
        y: Y coordinate in world frame (meters)
        resolution_m: Cell size in meters
        origin_x: Map origin X in meters
        origin_y: Map origin Y in meters

    Returns:
        Tuple of (grid_x, grid_y) in cells
    """
    grid_x = int((x + origin_x) / resolution_m)
    grid_y = int((y + origin_y) / resolution_m)
    return grid_x, grid_y


def grid_to_world(
    grid_x: int, grid_y: int, resolution_m: float, origin_x: float, origin_y: float
) -> tuple[float, float]:
    """
    Convert grid coordinates (cells) to world coordinates (meters).

    Args:
        grid_x: Grid X coordinate in cells
        grid_y: Grid Y coordinate in cells
        resolution_m: Cell size in meters
        origin_x: Map origin X in meters
        origin_y: Map origin Y in meters

    Returns:
        Tuple of (x, y) in meters
    """
    x = grid_x * resolution_m - origin_x
    y = grid_y * resolution_m - origin_y
    return x, y


def is_valid_cell(grid_x: int, grid_y: int, width: int, height: int) -> bool:
    """Check if grid coordinates are within map bounds"""
    return 0 <= grid_x < width and 0 <= grid_y < height


def is_traversable(grid, grid_x: int, grid_y: int, width: int, height: int, allow_unknown: bool = True) -> bool:
    """
    Check if a cell is traversable (not occupied).

    Args:
        grid: Occupancy grid (numpy array or list of lists)
        grid_x: Grid X coordinate
        grid_y: Grid Y coordinate
        width: Grid width in cells
        height: Grid height in cells
        allow_unknown: Whether to allow traversing unknown cells

    Returns:
        True if cell can be traversed
    """
    if not is_valid_cell(grid_x, grid_y, width, height):
        return False

    cell_value = grid[grid_y][grid_x]

    if cell_value == CELL_OCCUPIED:
        return False

    if cell_value == CELL_UNKNOWN and not allow_unknown:
        return False

    return True


def get_neighbors(x: int, y: int) -> list[tuple[int, int, float]]:
    """
    Get 8-connected neighbors with costs.

    Returns:
        List of (dx, dy, cost) tuples
    """
    # 8-connected grid: orthogonal moves cost 1.0, diagonal moves cost sqrt(2)
    sqrt_2 = math.sqrt(2)
    neighbors = [
        (0, 1, 1.0),  # North
        (1, 0, 1.0),  # East
        (0, -1, 1.0),  # South
        (-1, 0, 1.0),  # West
        (1, 1, sqrt_2),  # Northeast
        (1, -1, sqrt_2),  # Southeast
        (-1, -1, sqrt_2),  # Southwest
        (-1, 1, sqrt_2),  # Northwest
    ]
    return [(x + dx, y + dy, cost) for dx, dy, cost in neighbors]


def reconstruct_path(node: Node) -> list[tuple[int, int]]:
    """Reconstruct path from goal node to start"""
    path = []
    current = node
    while current is not None:
        path.append((current.x, current.y))
        current = current.parent
    return list(reversed(path))


def simplify_path(path: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """
    Simplify path by removing intermediate points on straight lines.

    Args:
        path: List of (x, y) grid coordinates

    Returns:
        Simplified path with waypoints
    """
    if len(path) <= 2:
        return path

    simplified = [path[0]]

    for i in range(1, len(path) - 1):
        prev_x, prev_y = simplified[-1]
        curr_x, curr_y = path[i]
        next_x, next_y = path[i + 1]

        # Calculate direction vectors
        dx1 = curr_x - prev_x
        dy1 = curr_y - prev_y
        dx2 = next_x - curr_x
        dy2 = next_y - curr_y

        # Normalize directions
        len1 = math.sqrt(dx1**2 + dy1**2) or 1.0
        len2 = math.sqrt(dx2**2 + dy2**2) or 1.0

        dx1, dy1 = dx1 / len1, dy1 / len1
        dx2, dy2 = dx2 / len2, dy2 / len2

        # If direction changed significantly, keep this point
        if abs(dx1 - dx2) > 0.01 or abs(dy1 - dy2) > 0.01:
            simplified.append(path[i])

    simplified.append(path[-1])
    return simplified


def find_path_grid(
    grid,
    start_x: int,
    start_y: int,
    goal_x: int,
    goal_y: int,
    width: int,
    height: int,
    allow_unknown: bool = True,
) -> list[tuple[int, int]] | None:
    """
    Find path using A* algorithm on grid coordinates.

    Args:
        grid: Occupancy grid (2D array)
        start_x: Start grid X coordinate
        start_y: Start grid Y coordinate
        goal_x: Goal grid X coordinate
        goal_y: Goal grid Y coordinate
        width: Grid width in cells
        height: Grid height in cells
        allow_unknown: Whether to allow traversing unknown cells

    Returns:
        List of (grid_x, grid_y) coordinates forming path, or None if no path found
    """
    # Validate start and goal
    if not is_traversable(grid, start_x, start_y, width, height, allow_unknown):
        return None

    if not is_traversable(grid, goal_x, goal_y, width, height, allow_unknown):
        return None

    # Initialize A*
    start_node = Node(start_x, start_y, 0.0, heuristic(start_x, start_y, goal_x, goal_y))
    open_set = [start_node]
    closed_set = set()
    g_scores = {(start_x, start_y): 0.0}

    while open_set:
        current = heapq.heappop(open_set)

        # Goal reached
        if current.x == goal_x and current.y == goal_y:
            path = reconstruct_path(current)
            return simplify_path(path)

        # Already processed
        if (current.x, current.y) in closed_set:
            continue

        closed_set.add((current.x, current.y))

        # Explore neighbors
        for nx, ny, cost in get_neighbors(current.x, current.y):
            if not is_traversable(grid, nx, ny, width, height, allow_unknown):
                continue

            if (nx, ny) in closed_set:
                continue

            tentative_g = current.g + cost

            # If we found a better path to this neighbor
            if (nx, ny) not in g_scores or tentative_g < g_scores[(nx, ny)]:
                g_scores[(nx, ny)] = tentative_g
                h = heuristic(nx, ny, goal_x, goal_y)
                neighbor_node = Node(nx, ny, tentative_g, h, current)
                heapq.heappush(open_set, neighbor_node)

    # No path found
    return None


def find_path(
    grid_data: dict,
    start_pose: tuple[float, float],
    goal_pose: tuple[float, float],
    allow_unknown: bool = True,
) -> list[tuple[float, float]] | None:
    """
    Find path from start to goal using A* algorithm.

    Args:
        grid_data: Dictionary containing:
            - 'grid': 2D occupancy grid array
            - 'width_cells': Grid width in cells
            - 'height_cells': Grid height in cells
            - 'resolution_m': Cell size in meters
            - 'origin_x': Map origin X in meters
            - 'origin_y': Map origin Y in meters
        start_pose: Starting position (x, y) in meters
        goal_pose: Goal position (x, y) in meters
        allow_unknown: Whether to allow traversing unknown cells

    Returns:
        List of (x, y) waypoints in meters, or None if no path found
    """
    grid = grid_data["grid"]
    width = grid_data["width_cells"]
    height = grid_data["height_cells"]
    resolution = grid_data["resolution_m"]
    origin_x = grid_data["origin_x"]
    origin_y = grid_data["origin_y"]

    # Convert world coordinates to grid coordinates
    start_x, start_y = world_to_grid(start_pose[0], start_pose[1], resolution, origin_x, origin_y)
    goal_x, goal_y = world_to_grid(goal_pose[0], goal_pose[1], resolution, origin_x, origin_y)

    # Find path in grid coordinates
    grid_path = find_path_grid(grid, start_x, start_y, goal_x, goal_y, width, height, allow_unknown)

    if grid_path is None:
        return None

    # Convert grid path to world coordinates
    world_path = [grid_to_world(gx, gy, resolution, origin_x, origin_y) for gx, gy in grid_path]

    return world_path
