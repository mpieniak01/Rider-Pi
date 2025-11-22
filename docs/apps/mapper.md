# Mapper — SLAM Mapping (Stage 3)

The Mapper module builds a real-time occupancy grid map of the robot's environment using SLAM (Simultaneous Localization and Mapping) techniques.

## Overview

- **Location**: `apps/mapper/`
- **Purpose**: Build occupancy grid map from robot pose and obstacle detections
- **Stage**: Reconnaissance Stage 3 — Real-time mapping
- **Dependencies**: 
  - Subscribes to `robot.pose` (from odometry)
  - Subscribes to `vision.obstacle.data` (from vision with depth estimation)
- **Publishes**: `mapper.map.data` (occupancy grid)

## Key Features

- **Occupancy Grid**: 2D grid representing free/occupied/unknown space
- **Coordinate Transformation**: Converts robot-local obstacle detections to global map coordinates
- **Cell States**: 
  - `0` = unknown
  - `1-50` = free space (low probability of obstacle)
  - `51-100` = occupied (high probability of obstacle)
- **Obstacle Inflation**: Expands obstacles by configurable radius for safer navigation

## Configuration

Environment variables for map parameters:

| Variable | Default | Description |
|----------|---------|-------------|
| `MAPPER_MAP_WIDTH_M` | `10.0` | Map width in meters |
| `MAPPER_MAP_HEIGHT_M` | `10.0` | Map height in meters |
| `MAPPER_MAP_RESOLUTION_M` | `0.05` | Cell size in meters (5cm) |
| `MAPPER_ROBOT_INIT_X` | `0.0` | Initial robot X position |
| `MAPPER_ROBOT_INIT_Y` | `0.0` | Initial robot Y position |
| `MAPPER_INFLATION_RADIUS` | `0.1` | Obstacle inflation radius (m) |

## Coordinate Systems

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

## Usage

### Running the Mapper

**Manual start:**
```bash
python3 apps/mapper/main.py
```

**Via systemd:**
```bash
sudo systemctl start rider-mapper
```

### Integration with Navigator

The mapper provides map data to the navigator for path planning (Stage 4: Return-to-Home).

**Map Request:**
```python
# Navigator requests current map
bus.publish("navigator.map.request", {"requester": "navigator"})

# Mapper responds with map data
bus.subscribe("mapper.map.data", handle_map_data)
```

## Data Flow

```
┌──────────────┐     robot.pose     ┌──────────────┐
│  Odometry    │────────────────────▶│              │
│  (x,y,theta) │                     │    Mapper    │
└──────────────┘                     │              │
                                     │  • Transform │
┌──────────────┐  vision.obstacle   │    coords    │
│   Vision     │────────────────────▶│  • Update    │
│ (depth est.) │                     │    grid      │
└──────────────┘                     │  • Inflate   │
                                     └──────┬───────┘
                                            │
                                            ▼
                                     mapper.map.data
                                     (occupancy grid)
```

## Implementation

**Main Components:**
- `main.py` — Entry point, ZMQ subscriptions
- `mapper_core.py` — Core SLAM logic
- `occupancy_grid.py` — Grid data structure
- `coordinate_transform.py` — Coordinate conversions

**Key Methods:**
- `update_map(pose, obstacles)` — Update grid with new observations
- `transform_obstacle(pose, local_angle, distance)` — Convert to global coords
- `inflate_obstacles(radius)` — Expand obstacle cells
- `get_map_data()` — Export grid for path planning

## Testing

```bash
# Unit tests
pytest tests/test_mapper.py -v

# Integration test with odometry and vision
pytest tests/test_mapper_integration.py -v
```

## Future Enhancements

- Loop closure detection
- Graph-based SLAM (pose graph optimization)
- 3D occupancy mapping
- Map persistence and loading

## Related Documentation

- [Architecture](../ARCHITECTURE.md#4b-mapper-slam-mapping)
- [Odometry](odometry.md) — Position tracking (Stage 2)
- [Navigator](navigator.md) — Path planning with map (Stage 4)
- [Vision](vision.md) — Depth estimation for mapping
