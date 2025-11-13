# Mapper Module — Occupancy Grid SLAM

## Overview

The **Mapper** module implements Stage 3 of the Rekonesans (Reconnaissance) epic. It builds a real-time occupancy grid map by fusing robot position data from odometry with obstacle data from the vision system.

## Architecture

### Component: `apps/mapper/main.py`

The mapper consists of two main classes:

1. **`OccupancyGrid`**: 2D grid representation of the environment
2. **`Mapper`**: Main mapping logic that coordinates data from multiple sources

### Data Flow

```
[Odometry] --robot.pose--> [Mapper] <--vision.obstacle.data-- [Vision]
                              |
                              v
                      [Occupancy Grid]
                         (in-memory)
```

### Bus Topics

**Subscribed Topics:**
- `robot.pose` - Robot position and orientation from odometry (Stage 2)
- `vision.obstacle.data` - Obstacle detections with distance from vision
- `navigator.map.request` - **NEW in Stage 4**: Map data requests from navigator

**Published Topics:**
- `mapper.map.data` - **NEW in Stage 4**: Occupancy grid map published on request

## Occupancy Grid

### Structure

The occupancy grid is a 2D numpy array where each cell represents a small area of the environment (default: 5cm × 5cm).

**Cell Values:**
- `0` (CELL_FREE) - Free space, no obstacle
- `127` (CELL_UNKNOWN) - Unknown/unexplored space
- `255` (CELL_OCCUPIED) - Occupied by obstacle

### Configuration

Environment variables control map parameters:

| Variable | Default | Description |
|----------|---------|-------------|
| `MAPPER_MAP_WIDTH_M` | `10.0` | Map width in meters |
| `MAPPER_MAP_HEIGHT_M` | `10.0` | Map height in meters |
| `MAPPER_MAP_RESOLUTION_M` | `0.05` | Cell size in meters (5cm) |
| `MAPPER_ROBOT_INIT_X` | `0.0` | Initial robot X position |
| `MAPPER_ROBOT_INIT_Y` | `0.0` | Initial robot Y position |
| `MAPPER_INFLATION_RADIUS` | `0.1` | Obstacle inflation radius (m) |
| `MAPPER_LOG_LEVEL` | `INFO` | Logging level |

### Coordinate Systems

**World Coordinates:**
- Origin at center of map
- X-axis points east (right)
- Y-axis points north (up)
- Units: meters

**Grid Coordinates:**
- Origin at top-left corner
- X-axis points right
- Y-axis points down
- Units: cells

### Coordinate Transformation

The mapper performs coordinate transformations:

1. **Robot Local → Global**: Transforms obstacle detections from robot-relative coordinates to global map coordinates
   ```
   global_angle = robot_theta + local_angle
   global_x = robot_x + distance * cos(global_angle)
   global_y = robot_y + distance * sin(global_angle)
   ```

2. **World → Grid**: Converts metric coordinates to grid cells
   ```
   grid_x = int((world_x + origin_x) / resolution)
   grid_y = int((world_y + origin_y) / resolution)
   ```

## Usage

### Running the Mapper

**Manual start:**
```bash
python3 apps/mapper/main.py
```

**Systemd service:**
```bash
sudo systemctl start rider-mapper
sudo systemctl status rider-mapper
```

**Auto-start on boot:**
```bash
sudo systemctl enable rider-mapper
```

### Dependencies

The mapper depends on:
- `rider-broker.service` - ZMQ message broker
- `rider-odometry.service` - Robot position tracking

## Implementation Details

### Obstacle Mapping

When obstacle data arrives from vision:

1. Get current robot pose (x, y, theta)
2. For each obstacle (angle, distance):
   - Transform from robot-local to global coordinates
   - Convert to grid cell coordinates
   - Mark cell as occupied
   - Optionally inflate obstacle (mark nearby cells)

### Obstacle Inflation

To provide safety margins, obstacles can be inflated by a configurable radius (default 10cm). This marks cells around obstacles as occupied, creating a buffer zone.

### Statistics

The mapper tracks and periodically logs:
- Total cells in map
- Occupied cells count
- Free cells count
- Unknown/unexplored cells count
- Percentage of map explored
- Number of obstacles processed

## Testing

Comprehensive test suite in `tests/test_mapper.py`:

**Grid Tests:**
- Initialization
- World-to-grid coordinate conversion
- Cell validity checking
- Obstacle marking
- Inflation

**Mapper Tests:**
- Robot pose handling
- Obstacle data processing
- Coordinate transformations
- Edge cases (invalid distances, empty data)

Run tests:
```bash
pytest tests/test_mapper.py -v
```

## Integration with Rekonesans Epic

### Stage 1: Navigator
Provides autonomous exploration capability (obstacle avoidance)

### Stage 2: Odometry
Provides robot position (x, y, theta) on `robot.pose` topic

### Stage 3: Mapper (This Module)
Consumes odometry and vision data to build occupancy grid

### Stage 4: Return to Home (NEW)
**Mapper now provides map data to navigator for path planning:**
- Navigator requests map via `navigator.map.request` topic
- Mapper responds with occupancy grid on `mapper.map.data` topic
- Navigator uses map for A* pathfinding to return to start position

## Map Data Format (Stage 4)

When navigator requests the map, mapper publishes the following data structure:

```json
{
  "grid": [[0, 0, 127, ...], ...],  // 2D array of cell values
  "width_cells": 200,                // Grid width in cells
  "height_cells": 200,               // Grid height in cells
  "resolution_m": 0.05,              // Cell size in meters
  "origin_x": 5.0,                   // Map origin X offset
  "origin_y": 5.0,                   // Map origin Y offset
  "width_m": 10.0,                   // Total map width
  "height_m": 10.0,                  // Total map height
  "ts": 1234567890.123               // Timestamp
}
```

**Cell Values:**
- `0` - Free space (traversable)
- `127` - Unknown (can be traversed if configured)
- `255` - Occupied (obstacle, not traversable)

## Design Inspiration

The occupancy grid structure is inspired by `sim/world.py` but implemented for dynamic, real-time mapping:
- `sim/world.py`: Static map loaded from file
- `apps/mapper/main.py`: Dynamic map built from sensor data

## Limitations and Future Work

**Current Limitations:**
- Map is in-memory only (not persisted to disk)
- No probabilistic occupancy (cells are binary: occupied or free)
- Fixed map size (no dynamic expansion)
- No loop closure detection

**Stage 4 Enhancements (IMPLEMENTED):**
- ✅ Map publishing on request for path planning
- ✅ Integration with navigator for return-to-home

**Future Enhancements:**
- Save/load map to/from disk
- Publish map updates on bus for real-time visualization
- Probabilistic occupancy grid (0-100% confidence)
- Dynamic map expansion as robot explores
- Loop closure detection for improved accuracy
- Map merging for multi-robot scenarios
- Integration with localization (full SLAM)

## See Also

- `docs/modules/navigator.md` - Stage 1: Obstacle avoidance
- `docs/modules/odometry.md` - Stage 2: Position tracking
- `sim/world.py` - Simulator world and map structure
- `ARCHITECTURE.md` - Overall system architecture
