# Rider-Pi 2D Simulator

A 2D simulator for testing Rider-Pi navigation algorithms without physical hardware.

## Features

- **Virtual Robot**: Simulates robot dynamics (position, orientation, velocities)
- **MQTT/ZMQ Integration**: Receives control commands via ZMQ message bus
- **Physics Simulation**: Realistic linear and angular motion
- **Map System**: Text-based maps with wall detection
- **Visual Rendering**: Pygame-based visualization with telemetry panel
- **Virtual Sensors**: Gyroscope and camera with ZMQ publishing

## Requirements

```bash
pip install pygame pyzmq
```

## Quick Start

### 1. Start the ZMQ Broker

The broker proxies messages between publishers and subscribers:

```bash
python3 services/broker.py
```

This starts:
- Frontend (XSUB): `tcp://*:5555` - for publishers
- Backend (XPUB): `tcp://*:5556` - for subscribers

### 2. Run the Simulator

```bash
python3 run_simulation.py
```

The simulator will:
- Load the map from `sim/maps/simple.txt` (or set `SIM_MAP` env var)
- Place the robot at the 'R' marker position
- Open a pygame window with map view and telemetry panel
- Subscribe to `motion` topic on the ZMQ bus

### 3. Control the Robot

**Option A: Keyboard Control**

```bash
python3 tools/sim_keyboard_control.py
```

Controls:
- `W` - Move forward
- `S` - Move backward
- `A` - Turn left
- `D` - Turn right
- `Space` - Stop
- `Q/ESC` - Quit

**Option B: Publish Commands Directly**

```bash
python3 tools/pub.py motion '{"type":"drive","lx":1.0,"az":0.0}'
python3 tools/pub.py motion '{"type":"stop"}'
```

**Option C: Use Existing Motion Control**

The simulator is compatible with the existing motion control infrastructure:

```bash
# Send commands to the motion topic
python3 tools/send_cmd.py motion '{"type":"drive","lx":0.5,"az":0.3}'
```

## Map Format

Maps are text files where:
- `#` = Wall
- ` ` or `.` = Floor
- `R` = Robot start position

Example:
```
##########
#        #
#  R     #
#   ##   #
#        #
##########
```

## Environment Variables

### Simulator
- `SIM_MAP` - Path to map file (default: `sim/maps/simple.txt`)
- `SIM_LOG_LEVEL` - Logging level (default: `INFO`)

### ZMQ Bus
- `BUS_PUB_ADDR` - Publisher address (default: `tcp://127.0.0.1:5555`)
- `BUS_SUB_ADDR` - Subscriber address (default: `tcp://127.0.0.1:5556`)
- `MOTION_TOPIC` - Control topic name (default: `motion`)

### Sensors
- `GYRO_TOPIC` - Gyro data topic (default: `sensor.gyro`)
- `CAMERA_TOPIC` - Camera data topic (default: `sensor.camera`)

## Command Format

Commands are JSON messages sent to the `motion` topic:

**Drive Command:**
```json
{
  "type": "drive",
  "lx": 1.0,    // Linear velocity (-1.0 to 1.0)
  "az": 0.5     // Angular velocity (-1.0 to 1.0)
}
```

**Stop Command:**
```json
{
  "type": "stop"
}
```

## Robot Dynamics

- **Linear velocity**: Scaled by 0.3 m/s (configurable in code)
- **Angular velocity**: Scaled by 1.5 rad/s (configurable in code)
- **Position update**: Uses standard differential drive kinematics
- **Angle normalization**: Angles are kept in [-π, π] range

## Telemetry

The simulator displays real-time telemetry in the side panel:
- Position (X, Y) in meters
- Orientation (angle) in degrees
- Linear velocity (m/s)
- Angular velocity (rad/s)
- Camera first-person view

Virtual sensors publish data to ZMQ:
- **Gyro**: Publishes orientation (yaw, roll, pitch) at 10 Hz
- **Camera**: Publishes frame metadata at 5 Hz

## Testing

Run unit tests:
```bash
python3 tests/test_simulator_robot.py
```

Run integration test (requires broker):
```bash
python3 tests/test_simulator_mqtt.py
```

## Architecture

```
┌──────────────┐
│   Publisher  │ (keyboard control, motion commands)
│ (PUB socket) │
└──────┬───────┘
       │ connects to tcp://127.0.0.1:5555
       ▼
┌──────────────┐
│   Broker     │ (ZMQ proxy)
│ XSUB ↔ XPUB  │
└──────┬───────┘
       │ binds to tcp://*:5556
       ▼
┌──────────────┐
│  Simulator   │
│ (SUB socket) │
│   + Robot    │
│   + World    │
│   + Sensors  │
└──────────────┘
```

## Troubleshooting

**Simulator doesn't respond to commands:**
- Check that the broker is running
- Verify the correct ZMQ addresses (check `BUS_PUB_ADDR` and `BUS_SUB_ADDR`)
- Check that commands are sent to the correct topic (default: `motion`)

**Pygame window doesn't open:**
- Install pygame: `pip install pygame`
- If running over SSH, set `DISPLAY` or use headless mode

**Robot doesn't move:**
- Commands are scaled (lx=1.0 → 0.3 m/s actual)
- Check telemetry panel for current velocities
- Verify physics is updating (check FPS in window title)
