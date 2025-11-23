# Navigator — Autonomous Navigation

The Navigator module provides autonomous exploration and navigation capabilities for the Rider-Pi robot.

## Overview

- **Location**: `apps/navigator/`
- **Purpose**: Autonomous obstacle avoidance and path planning
- **Stages**:
  - **Stage 1**: Reactive obstacle avoidance (STOP and AVOID strategies)
  - **Stage 4**: Return-to-home using A* pathfinding with occupancy grid map
- **Dependencies**:
  - Subscribes to `vision.obstacle` (obstacle detection)
  - Subscribes to `mapper.map.data` (for path planning)
- **Publishes**: `navigator.state`, `navigator.control`, `motion.move`

## Key Features

- **Reactive Navigation**: Immediate response to obstacles
- **Two Strategies**:
  - **STOP**: Stop immediately when obstacle detected
  - **AVOID**: Turn to avoid obstacle and continue
- **State Machine**: Manages exploration, avoidance, and return-to-home behaviors
- **Path Planning**: A* algorithm for optimal return-to-home route
- **Web Integration**: Control via REST API and web interface

## State Machine

```
                    ┌─────────────┐
                    │    IDLE     │
                    └──────┬──────┘
                           │ start
                ┌──────────┴──────────┐
                │                     │
                ↓                     │
        ┌───────────────┐             │
        │  EXPLORING    │             │
        └───┬───────────┘             │
            │                         │
            ├─obstacle+STOP──→ STOPPED
            │                    │    │
            ├─obstacle+AVOID──→ AVOIDING
            │                    │    │
            └─return_home───→ RETURNING_HOME
                               │     │
                               ├─obstacle─→ PATH_BLOCKED
                               │            │
                               └─goal───────┘
                                    stop
```

## Navigation Strategies

### STOP Strategy

**Behavior**: Stop immediately when obstacle detected

**Use case**: Safe exploration in unknown or crowded environments

**Configuration**:
```bash
# Via API
POST /api/navigator/config
{
  "strategy": "STOP",
  "obstacle_threshold": 0.5
}
```

### AVOID Strategy

**Behavior**: Turn to avoid obstacle and continue exploration

**Use case**: Continuous exploration with dynamic avoidance

**Configuration**:
```bash
# Via API
POST /api/navigator/config
{
  "strategy": "AVOID",
  "obstacle_threshold": 0.5,
  "avoid_angle": 45
}
```

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `NAVIGATOR_STRATEGY` | `STOP` | Navigation strategy (STOP/AVOID) |
| `NAVIGATOR_OBSTACLE_THRESHOLD` | `0.5` | Obstacle detection threshold |
| `NAVIGATOR_AVOID_ANGLE` | `45` | Turn angle for AVOID strategy (degrees) |
| `NAVIGATOR_SPEED` | `0.3` | Forward movement speed (0.0-1.0) |
| `NAVIGATOR_LOG_LEVEL` | `INFO` | Logging level |

## API Endpoints

### Start Navigation

```bash
POST /api/navigator/start
{
  "strategy": "AVOID"
}
```

### Stop Navigation

```bash
POST /api/navigator/stop
```

### Update Configuration

```bash
POST /api/navigator/config
{
  "strategy": "AVOID",
  "obstacle_threshold": 0.6,
  "speed": 0.25
}
```

### Get Status

```bash
GET /api/navigator/status

Response:
{
  "state": "EXPLORING",
  "strategy": "AVOID",
  "obstacle_detected": false,
  "position": {"x": 1.2, "y": 0.8, "theta": 0.5}
}
```

### Return to Home

```bash
POST /api/navigator/return_home

# Triggers path planning using map from mapper
# Navigates back to starting position (0, 0)
```

## Usage

### Manual Start

```bash
python3 apps/navigator/main.py
```

### Via systemd

```bash
sudo systemctl start rider-navigator
```

### Via Web Interface

1. Open `http://robot-ip:8080/control.html`
2. Navigate to **Autonomous Navigation** section
3. Select strategy (STOP/AVOID)
4. Click **Start Navigation**
5. Click **Return to Home** when ready

## Data Flow

```
┌──────────────┐  vision.obstacle  ┌──────────────┐
│   Vision     │──────────────────▶│              │
│   System     │                    │  Navigator   │
└──────────────┘                    │              │
                                    │  • Strategy  │
┌──────────────┐  robot.pose       │  • State     │
│  Odometry    │──────────────────▶│    Machine   │
└──────────────┘                    │  • Path      │
                                    │    Planning  │
┌──────────────┐  mapper.map.data  │              │
│   Mapper     │──────────────────▶│              │
└──────────────┘                    └──────┬───────┘
                                           │
                                           ▼
                                    motion.move
                                    (drive commands)
```

## Implementation

**Main Components:**
- `main.py` — Entry point, ZMQ subscriptions
- `navigator_core.py` — Core navigation logic
- `state_machine.py` — State management
- `strategies.py` — STOP and AVOID implementations
- `pathfinding.py` — A* algorithm for return-to-home

## Testing

```bash
# Unit tests
pytest tests/test_navigator.py -v

# Integration test
pytest tests/test_navigator_integration.py -v

# Simulation test
RIDER_SIMULATOR=1 python3 apps/navigator/main.py
```

## Future Enhancements

- **Stage 2**: Integration with odometry for dead reckoning
- **Stage 3**: Integration with mapper for SLAM
- **Dynamic Re-planning**: Adjust path if obstacles detected during return-to-home
- **Waypoint Navigation**: Navigate to arbitrary goal positions
- **Coverage Path Planning**: Systematic area exploration

## Related Documentation

- [Architecture](../ARCHITECTURE.md#4-navigator-autonomous-exploration)
- [Odometry](odometry.md) — Position tracking
- [Mapper](mapper.md) — SLAM mapping
- [Vision](vision.md) — Obstacle detection
- [Web UI](../ui/control.md) — Control interface
