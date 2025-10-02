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
