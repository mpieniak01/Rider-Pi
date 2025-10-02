# Rider-Pi 2D Simulator

A standalone 2D simulator for Rider-Pi that allows testing navigation algorithms without physical hardware.

## Features

- **Real-time Physics Simulation**: Simulates robot movement with realistic kinematics
- **MQTT Integration**: Uses the same MQTT bus protocol as the real robot
- **Visual Feedback**: 
  - Top-down view of the robot and environment
  - First-person camera view with perspective rendering
  - Real-time telemetry display
- **Map Loading**: Load custom environments from simple text files
- **Sensor Publishing**: Virtual gyroscope and camera publish data to MQTT topics

## Quick Start

### Running the Simulator

```bash
python run_simulation.py
```

### Environment Variables

- `SIM_MAP`: Path to map file (default: `sim/maps/simple.txt`)
- `SIM_WIDTH`: Window width in pixels (default: 1280)
- `SIM_HEIGHT`: Window height in pixels (default: 720)
- `SIM_FPS`: Simulation frame rate (default: 30)
- `SIM_LOG_LEVEL`: Logging level (default: INFO)

### MQTT Topics

The simulator uses the same MQTT topics as the real robot:

**Subscribed (Inputs):**
- `motion` - Control commands: `{"type": "drive", "lx": 0.5, "az": 0.2}` or `{"type": "stop"}`

**Published (Outputs):**
- `rider.gyro.angle` - Robot orientation in degrees
- `rider.camera.frame` - Camera image as JPEG bytes

### Controlling the Robot

Use existing tools to control the simulated robot:

```bash
# Monitor MQTT traffic
python tools/bus_spy.py

# Send manual commands
python tools/send_cmd.py
```

Or publish commands directly:

```python
import zmq
import json

ctx = zmq.Context.instance()
pub = ctx.socket(zmq.PUB)
pub.connect("tcp://127.0.0.1:5555")

# Drive forward
pub.send_multipart([
    b"motion",
    json.dumps({"type": "drive", "lx": 0.5, "az": 0.0}).encode()
])

# Stop
pub.send_multipart([
    b"motion",
    json.dumps({"type": "stop"}).encode()
])
```

## Map Format

Maps are simple text files with the following characters:

- `X` - Wall/obstacle
- `R` - Robot start position
- `M` - Goal/target
- ` ` (space) - Empty space

Example:

```
XXXXXXXXXX
X        X
X   R    X
X        X
X    M   X
XXXXXXXXXX
```

### Available Maps

- `sim/maps/simple.txt` - Basic test environment
- `sim/maps/corridor.txt` - Long corridor
- `sim/maps/maze.txt` - Complex environment with obstacles

## Architecture

The simulator is completely independent from the `rider_pi` package and has no direct imports from it. It communicates solely through the MQTT bus, acting as a digital twin of the physical robot.

### Components

- **`sim/world.py`** - Main simulation environment and Pygame rendering
- **`sim/robot.py`** - Virtual robot with physics and MQTT control
- **`sim/sensors.py`** - Virtual gyroscope and camera with MQTT publishing
- **`run_simulation.py`** - Entry point script

## Development

### Testing

```bash
# Run simulator tests
pytest tests/test_simulator.py -v

# Run with specific map
SIM_MAP=sim/maps/maze.txt python run_simulation.py
```

### Linting

```bash
ruff check sim/ run_simulation.py
ruff format sim/ run_simulation.py
```

## Integration with Navigation Algorithms

The same navigation algorithm code can control both the simulator and real robot by simply connecting to the MQTT bus. No code changes are required.

Example:

```python
# This code works with both simulator and real robot
from common.bus import BusPub, BusSub

pub = BusPub()
sub = BusSub("rider.gyro.angle")

# Send movement command
pub.publish("motion", {"type": "drive", "lx": 0.5, "az": 0.0})

# Receive sensor data
for topic, payload in sub:
    print(f"Angle: {payload['angle']}")
```

## Keyboard Controls

- `ESC` - Quit simulation

Control commands must be sent via MQTT for realistic testing.
