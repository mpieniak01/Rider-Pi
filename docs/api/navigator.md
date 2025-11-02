# Navigator API

Autonomous navigation (Rekonesans mode) control endpoints.

## Base Path
`/api/navigator`

## Overview

The Navigator API controls the autonomous Rekonesans (reconnaissance) mode, which includes:
- **Stage 1**: Reactive obstacle avoidance with STOP and AVOID strategies
- **Stage 4**: Return-to-home navigation with A* pathfinding

## Endpoints

### POST /api/navigator/start
Start autonomous navigation in Rekonesans mode.

**Request Body:**
```json
{
  "strategy": "STOP"  // or "AVOID"
}
```

**Strategies:**
- `STOP` - Stop immediately when obstacle detected (safe mode)
- `AVOID` - Turn right and continue when obstacle detected (exploration mode)

**Response:**
```json
{
  "ok": true,
  "action": "start",
  "strategy": "STOP"
}
```

**Bus Topic:** `navigator.control`

**Example:**
```bash
curl -X POST http://robot-ip:8080/api/navigator/start \
  -H "Content-Type: application/json" \
  -d '{"strategy": "AVOID"}'
```

---

### POST /api/navigator/stop
Stop autonomous navigation.

**Request Body:** (empty or `{}`)

**Response:**
```json
{
  "ok": true,
  "action": "stop"
}
```

**Bus Topic:** `navigator.control`

**Example:**
```bash
curl -X POST http://robot-ip:8080/api/navigator/stop
```

---

### POST /api/navigator/config
Update navigator configuration at runtime.

**Request Body:**
```json
{
  "strategy": "AVOID",     // optional: "STOP" or "AVOID"
  "fwd_speed": 0.4,        // optional: forward speed (0.0-1.0)
  "turn_speed": 0.5,       // optional: turn speed (0.0-1.0)
  "turn_duration": 0.6,    // optional: turn duration (seconds)
  "cooldown": 1.0          // optional: cooldown after avoid (seconds)
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

**Bus Topic:** `navigator.control`

**Example:**
```bash
curl -X POST http://robot-ip:8080/api/navigator/config \
  -H "Content-Type: application/json" \
  -d '{"strategy": "AVOID", "fwd_speed": 0.4}'
```

---

### GET /api/navigator/status
Get navigator status information.

**Response:**
```json
{
  "ok": true,
  "note": "Status endpoint - subscribe to navigator.state topic for real-time updates",
  "topic": "navigator.state"
}
```

**Note:** For real-time status updates, subscribe to the `navigator.state` bus topic.

---

### POST /api/navigator/return_home
**NEW in Stage 4**: Trigger autonomous navigation back to starting position.

**Request Body:** (empty or `{}`)

**Response:**
```json
{
  "ok": true,
  "action": "return_home"
}
```

**Behavior:**
1. Stops current exploration activity
2. Requests occupancy grid map from mapper
3. Calculates optimal path using A* algorithm
4. Follows waypoints to return to origin (0, 0)
5. Stops if obstacle detected during return

**Bus Topics:**
- Publishes: `navigator.return_home.start`
- Publishes: `navigator.map.request` (requests map from mapper)
- Subscribes: `mapper.map.data` (receives map)
- Subscribes: `robot.pose` (current position from odometry)

**Example:**
```bash
curl -X POST http://robot-ip:8080/api/navigator/return_home
```

**Prerequisites:**
- `rider-odometry.service` must be running (for position tracking)
- `rider-mapper.service` must be running (for map data)
- Robot must have explored some area (map must exist)

---

## Navigator States

The navigator publishes state updates on the `navigator.state` bus topic:

```json
{
  "active": true,
  "state": "exploring",
  "strategy": "AVOID",
  "obstacle_present": false,
  "ts": 1234567890.123
}
```

**States:**
- `idle` - Navigator inactive
- `exploring` - Active exploration, moving forward
- `avoiding` - Turning to avoid obstacle (AVOID strategy)
- `stopped` - Stopped due to obstacle (STOP strategy) or manual stop
- `returning_home` - Navigating back to start position
- `path_blocked` - Obstacle detected during return-to-home

---

## Configuration Environment Variables

Default configuration can be set via environment variables:

```bash
NAVIGATOR_LOG_LEVEL=INFO          # Logging level
NAVIGATOR_STRATEGY=STOP           # Default strategy
NAVIGATOR_FWD_SPEED=0.3          # Forward speed (0.0-1.0)
NAVIGATOR_TURN_SPEED=0.4         # Turn speed (0.0-1.0)
NAVIGATOR_TURN_DURATION=0.5      # Turn duration (seconds)
NAVIGATOR_COOLDOWN=1.0           # Cooldown after avoid (seconds)
NAVIGATOR_AUTO_START=0           # Auto-start on launch (0=no, 1=yes)

# Path Following (Return to Home)
NAVIGATOR_WAYPOINT_TOLERANCE=0.15  # Distance to waypoint (meters)
NAVIGATOR_ANGLE_TOLERANCE=0.2      # Angle tolerance (radians ~11°)
NAVIGATOR_GOAL_TOLERANCE=0.1       # Final distance to goal (meters)
```

---

## Implementation

**Module:** `services/api_core/navigator_api.py`  
**Navigator Core:** `apps/navigator/main.py`  
**Pathfinding:** `apps/navigator/pathfinding.py`

**Bus Topics:**
- **Published:**
  - `navigator.control` - Control commands
  - `navigator.state` - State updates
  - `navigator.map.request` - Map requests
  - `navigator.return_home.start` - Return home trigger
  - `motion` - Movement commands

- **Subscribed:**
  - `vision.obstacle` - Obstacle detection
  - `robot.pose` - Robot position (odometry)
  - `mapper.map.data` - Occupancy grid map

---

## Dependencies

**Required Services:**
- `rider-broker.service` - ZMQ message broker
- `rider-vision.service` - Obstacle detection
- `rider-obstacle.service` - ROI obstacle detector

**Optional Services (for full Rekonesans functionality):**
- `rider-odometry.service` - Position tracking (Stage 2)
- `rider-mapper.service` - SLAM mapping (Stage 3)

---

## Web Interface

The navigator is controlled through the web interface at `http://robot-ip:8080/control.html`:

**Controls:**
- Checkbox to enable/disable Rekonesans mode
- Strategy selector (STOP / AVOID)
- "🏠 Powrót do Bazy" (Return to Home) button (appears when active)
- Real-time status badge showing current state

---

## See Also

- [Navigator Module Documentation](../modules/navigator.md) - Detailed module docs
- [Odometry Module](../modules/odometry.md) - Position tracking
- [Mapper Module](../modules/mapper.md) - SLAM mapping
- [Vision Module](../apps/vision.md) - Obstacle detection
- [Control API](control.md) - Basic movement control
