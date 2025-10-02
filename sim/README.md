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
=======
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
