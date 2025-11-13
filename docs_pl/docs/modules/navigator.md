# Navigator Module — Autonomous Rekonesans (Reconnaissance) Mode

## Overview

The Navigator module implements the **Rekonesans (Reconnaissance) Epic** for autonomous exploration and navigation. It provides:

- **Stage 1**: Reactive obstacle avoidance with STOP and AVOID strategies
- **Stage 4**: Return-to-home navigation with A* pathfinding

The navigator enables the Rider-Pi robot to autonomously explore an environment, avoid obstacles, build a mental map, and navigate back to its starting position.

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────────┐
│                     Web Interface                           │
│                   (web/control.html)                        │
│            • Start/Stop Rekonesans                          │
│            • Return to Home button                          │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP REST
                       ↓
┌─────────────────────────────────────────────────────────────┐
│                  Navigator API                              │
│            (services/api_core/navigator_api.py)             │
│  • /api/navigator/start                                     │
│  • /api/navigator/stop                                      │
│  • /api/navigator/return_home                               │
└──────────────────────┬──────────────────────────────────────┘
                       │ ZMQ Bus
                       ↓
┌─────────────────────────────────────────────────────────────┐
│                  Navigator Core                             │
│              (apps/navigator/main.py)                       │
│  ┌──────────────┐   ┌────────────┐   ┌──────────────────┐  │
│  │ State        │   │  Strategy  │   │  Bus Interface   │  │
│  │ Machine      │   │  STOP/     │   │  • Sub: obstacle │  │
│  │              │   │  AVOID     │   │  • Sub: control  │  │
│  │              │   │            │   │  • Sub: pose     │  │
│  │              │   │            │   │  • Sub: map      │  │
│  │              │   │            │   │  • Pub: state    │  │
│  │              │   │            │   │  • Pub: motion   │  │
│  └──────────────┘   └────────────┘   └──────────────────┘  │
│  ┌────────────────────────────────────────────────────────┐ │
│  │          Pathfinding (A*)                              │ │
│  │      (apps/navigator/pathfinding.py)                   │ │
│  │  • Grid-based A* search                                │ │
│  │  • Path simplification                                 │ │
│  │  • World ↔ Grid coordinate conversion                 │ │
│  └────────────────────────────────────────────────────────┘ │
└───────┬─────────────────────────────────┬──────────┬────────┘
        │                                 │          │
        │ vision.obstacle                 │ pose     │ map request
        ↓                                 ↓          ↓
┌──────────────────┐      ┌───────────────────┐  ┌──────────┐
│  Vision System   │      │  Odometry System  │  │  Mapper  │
│  (obstacle_roi)  │      │  (x, y, theta)    │  │  (SLAM)  │
└──────────────────┘      └───────────────────┘  └──────────┘
```

### State Machine

```
                                    ┌─────────────────┐
                                    │   IDLE          │
                                    └────┬────────────┘
                                         │ start
                    ┌────────────────────┴────────────┐
                    │                                 │
                    ↓                                 │
            ┌───────────────┐                         │
            │  EXPLORING    │                         │
            └───┬───────────┘                         │
                │                                     │
                ├──obstacle+STOP──→ STOPPED           │
                │                     │               │
                ├──obstacle+AVOID──→ AVOIDING         │
                │                     │               │
                └──return_home───→ RETURNING_HOME     │
                                     │                │
                                     ├─obstacle─→ PATH_BLOCKED
                                     │                │
                                     └─goal_reached───┘
                                          stop
```

**States:**
- **IDLE**: Navigator inactive, waiting for start command
- **EXPLORING**: Active autonomous navigation, moving forward and avoiding obstacles
- **AVOIDING**: Turning to avoid detected obstacle (AVOID strategy only)
- **STOPPED**: Stopped due to obstacle (STOP strategy) or manual stop
- **RETURNING_HOME**: Navigating back to starting position using A* pathfinding
- **PATH_BLOCKED**: Obstacle detected during return-to-home, navigation stopped

### Navigation Strategies

#### STOP Strategy
- **Behavior**: Stop immediately when obstacle detected
- **Use Case**: Safe mode, testing, confined spaces
- **Implementation**: Sends motion.stop command on obstacle detection

#### AVOID Strategy  
- **Behavior**: Turn right and continue when obstacle detected
- **Use Case**: Open areas, continuous exploration
- **Implementation**: 
  - Sends turn command (az=-turn_speed)
  - Cooldown period prevents rapid oscillation
  - Resumes forward motion after turn

## Configuration

### Environment Variables

```bash
# Navigator Core
NAVIGATOR_LOG_LEVEL=INFO          # Logging level (DEBUG, INFO, WARNING, ERROR)
NAVIGATOR_STRATEGY=STOP           # Default strategy (STOP, AVOID)
NAVIGATOR_FWD_SPEED=0.3          # Forward speed (0.0-1.0)
NAVIGATOR_TURN_SPEED=0.4         # Turn speed (0.0-1.0)
NAVIGATOR_TURN_DURATION=0.5      # Turn duration in seconds
NAVIGATOR_COOLDOWN=1.0           # Cooldown after avoid (seconds)
NAVIGATOR_AUTO_START=0           # Auto-start on launch (0=no, 1=yes)

# Path Following (Return to Home)
NAVIGATOR_WAYPOINT_TOLERANCE=0.15  # Distance to waypoint to consider reached (meters)
NAVIGATOR_ANGLE_TOLERANCE=0.2      # Angle tolerance for turning (radians, ~11 degrees)
NAVIGATOR_GOAL_TOLERANCE=0.1       # Distance to goal to consider reached (meters)
```

### Runtime Configuration

Configuration can be updated via API while navigator is running:

```bash
curl -X POST http://localhost:8080/api/navigator/config \
  -H "Content-Type: application/json" \
  -d '{
    "strategy": "AVOID",
    "fwd_speed": 0.4,
    "turn_speed": 0.5
  }'
```

## API Reference

### Start Navigation

```http
POST /api/navigator/start
Content-Type: application/json

{
  "strategy": "STOP"  // or "AVOID"
}
```

**Response:**
```json
{
  "ok": true,
  "action": "start",
  "strategy": "STOP"
}
```

### Stop Navigation

```http
POST /api/navigator/stop
```

**Response:**
```json
{
  "ok": true,
  "action": "stop"
}
```

### Update Configuration

```http
POST /api/navigator/config
Content-Type: application/json

{
  "strategy": "AVOID",
  "fwd_speed": 0.4,
  "turn_speed": 0.5
}
```

**Response:**
```json
{
  "ok": true,
  "action": "config",
  "config": {
    "strategy": "AVOID",
    "fwd_speed": 0.4,
    "turn_speed": 0.5
  }
}
```

### Get Status

```http
GET /api/navigator/status
```

**Response:**
```json
{
  "ok": true,
  "note": "Status endpoint - subscribe to navigator.state topic for real-time updates",
  "topic": "navigator.state"
}
```

### Return to Home

**NEW in Stage 4**

Triggers autonomous navigation back to the starting position (0, 0).

```http
POST /api/navigator/return_home
```

**Response:**
```json
{
  "ok": true,
  "action": "return_home"
}
```

**Behavior:**
1. Stops current exploration activity
2. Requests current occupancy grid map from mapper
3. Calculates optimal path using A* algorithm
4. Follows waypoints to return to origin (0, 0)
5. Stops if obstacle detected during return

## Bus Topics

### Subscribed Topics

#### `vision.obstacle`
Obstacle detection events from vision system.

**Payload:**
```json
{
  "type": "obstacle",
  "present": true,
  "confidence": 0.85,
  "edge_pct": 0.05,
  "ts": 1234567890.123
}
```

#### `navigator.control`
Control commands from API.

**Payload:**
```json
{
  "action": "start",      // or "stop", "config"
  "strategy": "AVOID",    // optional
  "config": {...},        // optional
  "ts": 1234567890.123
}
```

### Published Topics

#### `navigator.state`
Navigator state updates.

**Payload:**
```json
{
  "active": true,
  "state": "exploring",   // idle, exploring, avoiding, stopped, returning_home, path_blocked
  "strategy": "AVOID",
  "obstacle_present": false,
  "ts": 1234567890.123
}
```

#### `motion`
Motion control commands.

**Payload:**
```json
{
  "type": "drive",        // or "stop"
  "lx": 0.3,             // linear velocity (-1.0 to 1.0)
  "az": 0.0              // angular velocity (-1.0 to 1.0)
}
```

#### `navigator.map.request`
**NEW in Stage 4**: Request for occupancy grid map from mapper.

**Payload:**
```json
{
  "request_id": 1234567890.123,
  "ts": 1234567890.123
}
```

### Subscribed Topics (Stage 4 additions)

#### `robot.pose`
**NEW in Stage 4**: Current robot position from odometry system.

**Payload:**
```json
{
  "x": 1.5,               // X position in meters
  "y": 2.3,               // Y position in meters
  "theta": 0.785,         // Orientation in radians
  "theta_deg": 45.0,      // Orientation in degrees
  "ts": 1234567890.123
}
```

#### `mapper.map.data`
**NEW in Stage 4**: Occupancy grid map from mapper system.

**Payload:**
```json
{
  "grid": [[...]],        // 2D array of cell values (0=free, 255=occupied, 127=unknown)
  "width_cells": 200,     // Grid width in cells
  "height_cells": 200,    // Grid height in cells
  "resolution_m": 0.05,   // Cell size in meters
  "origin_x": 5.0,        // Map origin X in meters
  "origin_y": 5.0,        // Map origin Y in meters
  "width_m": 10.0,        // Map width in meters
  "height_m": 10.0,       // Map height in meters
  "ts": 1234567890.123
}
```

#### `navigator.return_home.start`
**NEW in Stage 4**: Command to start return-to-home sequence.

**Payload:**
```json
{
  "action": "return_home",
  "ts": 1234567890.123
}
```

## Usage

### From Web Interface

1. Navigate to `http://robot-ip:8080/control.html`
2. Locate the "Tryb Rekonesans (Autonomous)" section
3. Select desired strategy (STOP or AVOID)
4. Enable checkbox to start navigation
5. Monitor status badge and event log
6. **NEW**: Click "🏠 Powrót do Bazy" (Return to Home) button to navigate back to start
7. Disable checkbox to stop

**Return to Home Button:**
- Appears only when Rekonesans mode is active
- Stops exploration and begins autonomous navigation to origin
- Shows "Returning Home" status during navigation
- Robot stops automatically upon reaching home or if obstacle detected

### From Command Line

```bash
# Start navigator service
python3 -m apps.navigator.main

# Or with custom configuration
NAVIGATOR_STRATEGY=AVOID \
NAVIGATOR_FWD_SPEED=0.4 \
NAVIGATOR_TURN_SPEED=0.5 \
python3 -m apps.navigator.main

# Auto-start on launch
NAVIGATOR_AUTO_START=1 python3 -m apps.navigator.main
```

### From Python

```python
from apps.navigator.main import Navigator, Strategy

# Create navigator
nav = Navigator(strategy=Strategy.AVOID)

# Start exploration
nav.start()

# Change strategy
nav.set_strategy(Strategy.STOP)

# Stop
nav.stop()

# Run main loop
nav.run()
```

## Testing

### Unit Tests

```bash
# Run all navigator tests
pytest tests/test_navigator.py -v

# Run pathfinding tests (Stage 4)
pytest tests/test_navigator_pathfinding.py -v

# Run specific test
pytest tests/test_navigator.py::TestNavigator::test_obstacle_detected_stop_strategy -v

# Run all navigation-related tests
pytest tests/test_navigator.py tests/test_navigator_pathfinding.py tests/test_mapper.py tests/test_odometry.py -v
```

**Test Coverage:**
- Navigator state machine: 14 tests
- Pathfinding algorithms: 10 tests
- Mapper integration: 20 tests
- Odometry integration: 19 tests
- **Total: 67 tests**

### Integration Testing

```bash
# Full Rekonesans system test (Stages 1-4)
# 1. Start broker
python3 services/broker.py

# 2. Start vision system
python3 apps/vision/dispatcher.py

# 3. Start odometry (Stage 2)
python3 -m apps.odometry.main

# 4. Start mapper (Stage 3)
python3 -m apps.mapper.main

# 5. Start navigator (Stages 1 & 4)
python3 -m apps.navigator.main

# 6. Monitor via bus spy
python3 scripts/diag_bus-spy.py navigator

# Test return to home
curl -X POST http://localhost:8080/api/navigator/return_home
```

## Pathfinding System (Stage 4)

### A* Algorithm

The navigator uses A* pathfinding on the occupancy grid to find optimal paths back to the starting position.

**Features:**
- 8-connected grid search (diagonal moves allowed)
- Euclidean distance heuristic
- Path simplification to reduce waypoints
- Configurable unknown cell handling

**Algorithm:**
1. Request occupancy grid from mapper
2. Convert start/goal positions to grid coordinates
3. Run A* search to find path
4. Simplify path by removing collinear points
5. Convert grid path to world coordinates

### Path Following

Once a path is calculated, the navigator follows waypoints using a simple controller:

**Algorithm:**
1. Get next waypoint from path
2. Calculate angle to waypoint
3. If angle error > threshold: turn in place
4. Else: move forward toward waypoint
5. When waypoint reached: remove from path and proceed to next
6. When all waypoints reached: robot is home

**Parameters:**
- `WAYPOINT_TOLERANCE`: Distance to consider waypoint reached (default 0.15m)
- `ANGLE_TOLERANCE`: Angle error before turning (default 0.2 rad ≈ 11°)
- `GOAL_TOLERANCE`: Final distance to goal (default 0.1m)

### Obstacle Handling During Return

If an obstacle is detected while returning home:
1. Navigator transitions to `PATH_BLOCKED` state
2. Robot stops immediately
3. User must manually clear the obstacle
4. User can retry return-to-home (will recalculate path)

## Troubleshooting

### Navigator doesn't start

**Check:**
1. Broker is running: `systemctl status rider-broker`
2. API server is running: `systemctl status rider-api`
3. Vision system is publishing: `python3 scripts/diag_bus-spy.py vision`
4. Motion system is enabled: `MOTION_ENABLE=1`

### Robot doesn't move

**Check:**
1. Motion bridge is running
2. `MOTION_ENABLE=1` in environment
3. No E-Stop triggered
4. Motion commands are being published: `python3 scripts/diag_bus-spy.py motion`

### Obstacle detection not working

**Check:**
1. Vision dispatcher is running
2. Camera is accessible
3. Obstacle detection parameters are tuned
4. Check `/vision/obstacle` endpoint

## References

- [ARCHITECTURE.md](../../ARCHITECTURE.md) - System architecture
- [Epic Issue](https://github.com/mpieniak01/Rider-Pi/issues/XXX) - Full Rekonesans roadmap
- [Vision Module](vision.md) - Obstacle detection system
- [Motion Module](../apps/motion/main.py) - Motion control system
