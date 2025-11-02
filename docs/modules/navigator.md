# Navigator Module — Autonomous Rekonesans (Reconnaissance) Mode

## Overview

The Navigator module implements **Stage 1** of the Rekonesans (Reconnaissance) Epic: autonomous exploration with reactive obstacle avoidance. It enables the Rider-Pi robot to navigate autonomously, detecting and avoiding obstacles using the vision system.

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────────┐
│                     Web Interface                           │
│                   (web/control.html)                        │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP REST
                       ↓
┌─────────────────────────────────────────────────────────────┐
│                  Navigator API                              │
│            (services/api_core/navigator_api.py)             │
└──────────────────────┬──────────────────────────────────────┘
                       │ ZMQ Bus (navigator.control)
                       ↓
┌─────────────────────────────────────────────────────────────┐
│                  Navigator Core                             │
│              (apps/navigator/main.py)                       │
│  ┌──────────────┐   ┌────────────┐   ┌──────────────────┐  │
│  │ State        │   │  Strategy  │   │  Bus Interface   │  │
│  │ Machine      │   │  STOP/     │   │  • Sub: obstacle │  │
│  │              │   │  AVOID     │   │  • Sub: control  │  │
│  │              │   │            │   │  • Pub: state    │  │
│  └──────────────┘   └────────────┘   └──────────────────┘  │
└───────┬────────────────────────────────────────┬────────────┘
        │                                        │
        │ vision.obstacle                        │ motion
        ↓                                        ↓
┌──────────────────┐                    ┌──────────────────┐
│  Vision System   │                    │  Motion System   │
│  (obstacle_roi)  │                    │  (main.py)       │
└──────────────────┘                    └──────────────────┘
```

### State Machine

```
IDLE ──(start)──> EXPLORING ──(obstacle+STOP)──> STOPPED
  ↑                   │                              │
  │                   └──(obstacle+AVOID)──> AVOIDING
  │                                              │
  └─────────────────(stop)──────────────────────┘
```

**States:**
- **IDLE**: Navigator inactive, waiting for start command
- **EXPLORING**: Active autonomous navigation, moving forward
- **AVOIDING**: Turning to avoid detected obstacle (AVOID strategy only)
- **STOPPED**: Stopped due to obstacle (STOP strategy) or manual stop

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
# Navigator
NAVIGATOR_LOG_LEVEL=INFO          # Logging level (DEBUG, INFO, WARNING, ERROR)
NAVIGATOR_STRATEGY=STOP           # Default strategy (STOP, AVOID)
NAVIGATOR_FWD_SPEED=0.3          # Forward speed (0.0-1.0)
NAVIGATOR_TURN_SPEED=0.4         # Turn speed (0.0-1.0)
NAVIGATOR_TURN_DURATION=0.5      # Turn duration in seconds
NAVIGATOR_COOLDOWN=1.0           # Cooldown after avoid (seconds)
NAVIGATOR_AUTO_START=0           # Auto-start on launch (0=no, 1=yes)
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
  "state": "exploring",   // idle, exploring, avoiding, stopped
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

## Usage

### From Web Interface

1. Navigate to `http://robot-ip:8080/control.html`
2. Locate the "Tryb Rekonesans (Autonomous)" section
3. Select desired strategy (STOP or AVOID)
4. Enable checkbox to start navigation
5. Monitor status badge and event log
6. Disable checkbox to stop

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
# Run navigator tests
pytest tests/test_navigator.py -v

# Run specific test
pytest tests/test_navigator.py::TestNavigator::test_obstacle_detected_stop_strategy -v
```

### Integration Testing

```bash
# Test with real vision system
# 1. Start broker
python3 services/broker.py

# 2. Start vision (simulated or real)
python3 apps/vision/dispatcher.py

# 3. Start navigator
python3 -m apps.navigator.main

# 4. Monitor via bus spy
python3 scripts/diag_bus-spy.py navigator
```

## Future Enhancements (Stage 2-4)

### Stage 2: Odometry
- Position tracking `(x, y, theta)`
- IMU integration
- Velocity estimation
- Dead reckoning

### Stage 3: SLAM Mapping
- Depth estimation
- Occupancy grid generation
- Map publishing
- Real-time map updates

### Stage 4: Path Planning
- A* pathfinding
- Return-to-home navigation
- Waypoint following
- Dynamic re-planning

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
