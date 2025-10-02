# Rider-Pi 2D Simulator

# SIM-1: Simulator Core Implementation

## Overview
This implementation provides the foundational layer of the Rider-Pi 2D Simulator, including window initialization, map loading, and rendering capabilities.

## Features Implemented

### 1. Pygame Window Initialization
- **Window Size**: 1280x720 pixels (configurable via environment variables)
- **Title**: "Rider-Pi 2D Simulator"
- **FPS**: 30 (configurable via `SIM_FPS` environment variable)

### 2. Interface Panel Division
- **Map Panel**: 70% of window width (896px) - displays top-down view of the world
- **Side Panel**: 30% of window width (384px) - displays simulator information
- Visual divider line between panels

### 3. Map Loading System
The simulator can load maps from `.txt` files with the following format:
- `X` - Wall (rendered in gray)
- `R` - Robot start position (rendered in blue)
- `M` - Goal/Meta (rendered in green)
- ` ` - Empty space

### 4. Coordinate System
- Grid-based coordinate system
- Cell size: 30x30 pixels
- Automatic centering of map in main panel
- Coordinate conversion from grid to screen space

### 5. Example Maps
Two example maps are provided:

#### `sim/maps/simple.txt` (7x6 grid)
```
XXXXXXX
X R   X
X     X
X     X
X   M X
XXXXXXX
```

#### `sim/maps/map01.txt` (15x10 grid)
```
XXXXXXXXXXXXXXX
X             X
X             X
X      R      X
X             X
X             X
X             X
X      M      X
X             X
XXXXXXXXXXXXXXX
```

## File Structure
```
sim/
├── __init__.py          # Package initialization
├── world.py             # World class with rendering logic
└── maps/
    ├── simple.txt       # Simple test map
    └── map01.txt        # Default map

run_simulation.py        # Entry point for running the simulator

tests/
├── test_simulator_basic.py      # Unit tests
├── test_sim_screenshot.py       # Screenshot generation
└── verify_sim1_acceptance.py    # Acceptance criteria verification
```

## Usage

### Running the Simulator
```bash
python3 run_simulation.py
```

### Running Tests
```bash
# Run all simulator tests
pytest tests/test_simulator_basic.py -v

# Verify acceptance criteria
python3 tests/verify_sim1_acceptance.py
```

### Environment Variables
- `SIM_WIDTH`: Window width (default: 1280)
- `SIM_HEIGHT`: Window height (default: 720)
- `SIM_FPS`: Target frames per second (default: 30)
- `SDL_VIDEODRIVER`: Set to "dummy" for headless mode

### Creating Custom Maps
Create a `.txt` file with your map layout:
1. Use `X` for walls
2. Use `R` for the robot starting position
3. Use `M` for the goal/meta position
4. Use spaces for open areas
5. Save in `sim/maps/` directory

Example:
```python
from sim.world import World

world = World(map_file="sim/maps/your_map.txt")
```

## API Reference

### World Class

#### Constructor
```python
World(map_file: str = None)
```
- `map_file`: Path to the map file to load

#### Methods
- `load_map(filename: str)`: Load a map from a text file
- `grid_to_screen(x: float, y: float) -> tuple[int, int]`: Convert grid coordinates to screen coordinates
- `render()`: Render the complete simulation window
- `render_main_panel()`: Render the map panel
- `render_side_panel()`: Render the information panel
- `tick() -> float`: Advance simulation clock, returns delta time
- `handle_events() -> bool`: Process Pygame events, returns False on quit
- `quit()`: Clean up and close Pygame

#### Properties
- `walls`: List of wall positions as (x, y) tuples
- `goal`: Goal position as (x, y) tuple or None
- `start_pos`: Start position as (x, y) tuple or None
- `map_width`: Width of the loaded map in grid cells
- `map_height`: Height of the loaded map in grid cells

## Acceptance Criteria Status

✅ **AC1**: Uruchomienie `run_simulation.py` otwiera okno Pygame  
✅ **AC2**: W oknie widoczny jest podział na panel mapy i panel boczny  
✅ **AC3**: Mapa zdefiniowana w pliku `sim/maps/map01.txt` jest poprawnie narysowana na panelu mapy  
✅ **AC4**: Aplikację można zamknąć bez błędów  

All acceptance criteria have been verified and pass successfully.

## Test Coverage
- 7 unit tests covering:
  - World initialization
  - Map loading (simple and map01)
  - Map parsing
  - Rendering
  - Panel division
  - Coordinate conversion

All tests pass successfully.

## Dependencies
- `pygame>=2.5.0` (added to `requirements-dev.txt`)

## Future Extensions
This core implementation provides the foundation for:
- Robot simulation (planned for next iteration)
- Sensor simulation (cameras, gyroscopes)
- Physics simulation
- Interactive controls
- Telemetry display in side panel

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
