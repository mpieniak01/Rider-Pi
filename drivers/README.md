# Drivers - Hardware Abstraction Layer

This directory contains all hardware-specific drivers for the Rider-Pi robot, isolated from application logic.

## Structure

```
drivers/
├── xgo/              # XGO robot platform drivers
│   ├── adapter.py    # Physical hardware adapter
│   ├── sim.py        # Simulated adapter
│   └── __init__.py   # Factory function (get_robot_driver)
│
└── lcd/              # LCD display drivers
    ├── driver_ili9xx.py  # ILI9xx hardware driver
    ├── mock.py           # Mock driver for testing
    ├── sim.py            # Simulated driver
    ├── spi.py            # SPI interface driver
    ├── panel_cfg.py      # Panel configuration
    └── __init__.py       # Factory functions
```

## Usage

### XGO Robot Driver

#### Using the Factory (Recommended)
```python
from drivers.xgo import get_robot_driver

# Automatically selects physical or simulated based on RIDER_SIMULATOR
robot = get_robot_driver()

# Use the driver
robot.drive("forward", speed=0.3, dur=0.5)
robot.spin("left", speed=0.2, dur=0.3)
robot.stop()
```

#### Direct Import
```python
from drivers.xgo import XgoAdapter

robot = XgoAdapter()
```

### LCD Display Driver

#### Using the Factory (Recommended)
```python
from drivers.lcd import get_lcd_driver, PanelCfg

# Configure the panel
cfg = PanelCfg(rotate=270, bgr=True)

# Get driver (physical or simulated)
lcd = get_lcd_driver(cfg)

# Display an image
from PIL import Image
img = Image.new("RGB", (240, 240), color=(255, 0, 0))
lcd.ShowImage(img)
```

#### Direct Import
```python
from drivers.lcd import make_driver, PanelCfg

cfg = PanelCfg(rotate=270)
driver = make_driver("mock", cfg)  # or "spi"
```

## Simulation Mode

Set the `RIDER_SIMULATOR` environment variable to use simulated drivers:

```bash
# Enable simulation mode
export RIDER_SIMULATOR=1

# Run your application
python3 your_app.py
```

Or inline:
```bash
RIDER_SIMULATOR=1 python3 your_app.py
```

### Benefits of Simulation Mode

1. **No Hardware Required**: Test code without physical robot/display
2. **CI/CD Friendly**: Run tests in GitHub Actions, GitLab CI, etc.
3. **Safe Development**: No accidental motor activation
4. **Debugging**: Simulated drivers log all operations
5. **Frame Inspection**: LCD simulator saves frames to `/tmp/lcd_sim_*.png`

### Simulated Features

#### XGO Robot (`SimulatedXgoAdapter`)
- Logs all motion commands
- Provides mock sensor data (battery: 85%, IMU: 0/0/0)
- Same interface as physical driver
- No hardware dependencies

#### LCD Display (`SimulatedLCDRenderer`)
- Logs all display operations
- Optionally saves frames to disk
- Provides metadata in JSON
- Same interface as physical driver

## API Reference

### XgoAdapter / SimulatedXgoAdapter

```python
# Status
robot.ok() -> bool
robot.available_methods() -> list[str]

# Motion
robot.stop()
robot.drive(dir: "forward"|"backward", speed: 0..1, dur: float|None, *, block=False)
robot.spin(dir: "left"|"right", speed: 0..1, dur: float|None, deg: float|None, *, block=False)
robot.action(name: str)  # "sit", "stand", "wave", etc.

# Configuration
robot.set_stabilization(on: bool)
robot.enable_balance(on: bool)
robot.set_height(h: int)  # -30 to 55

# Sensors
robot.battery() -> float|None  # 0..1
robot.imu() -> dict|None       # {"roll": .., "pitch": .., "yaw": ..}

# LED
robot.led(idx: int, rgb: tuple[int, int, int])
```

### LCDRenderer / SimulatedLCDRenderer

```python
# Properties
lcd.width  -> int   # 240
lcd.height -> int   # 320

# Display
lcd.ShowImage(img: PIL.Image.Image)
```

### PanelCfg

```python
PanelCfg(
    rotate: int = 0,           # 0, 90, 180, 270
    bgr: bool = True,          # BGR vs RGB color order
    mx: bool = False,          # Mirror X
    mv: bool = False,          # Mirror Y
    fit: "fill"|"fit"|"stretch" = "fill"
)
```

## Examples

### Basic Motion
```python
from drivers.xgo import get_robot_driver

robot = get_robot_driver()

# Move forward for 1 second
robot.drive("forward", speed=0.5, dur=1.0, block=True)

# Turn 90 degrees
robot.spin("left", speed=0.3, deg=90, block=True)

# Stop
robot.stop()
```

### Display Pattern
```python
from drivers.lcd import get_lcd_driver, PanelCfg
from PIL import Image, ImageDraw

cfg = PanelCfg(rotate=270)
lcd = get_lcd_driver(cfg)

# Create image
img = Image.new("RGB", (240, 240), color=(0, 0, 128))
draw = ImageDraw.Draw(img)
draw.text((80, 110), "RIDER-PI", fill=(255, 255, 255))

# Display
lcd.ShowImage(img)
```

### Complete Demo
See `examples/demo_driver_factory.py` for a complete example.

## Testing

Run the driver tests:
```bash
# Test driver imports
python3 -m unittest tests.test_drivers_import

# Test simulation toggle
python3 -m unittest tests.test_simulation_toggle

# Verify hardware isolation
python3 tests/verify_hardware_isolation.py
```

## Migration Guide

### From Old Location to New

**Before (old)**:
```python
from apps.motion.xgo_adapter import XgoAdapter
from apps.ui.face.driver import make_driver
from apps.ui.face.panel_cfg import PanelCfg
```

**After (new)**:
```python
from drivers.xgo import XgoAdapter  # or get_robot_driver()
from drivers.lcd import make_driver, PanelCfg  # or get_lcd_driver()
```

**Note**: Old imports still work (backward compatibility shims in place).

### Using Factories

**Before (manual instantiation)**:
```python
from apps.motion.xgo_adapter import XgoAdapter

if os.getenv("SIMULATION_MODE"):
    robot = SimAdapter()
else:
    robot = XgoAdapter()
```

**After (factory function)**:
```python
from drivers.xgo import get_robot_driver

robot = get_robot_driver()  # Auto-selects based on RIDER_SIMULATOR
```

## Troubleshooting

### ImportError: No module named 'xgolib'
This is expected when using simulated drivers or when hardware libraries are not installed.
Use `RIDER_SIMULATOR=1` to use simulated drivers.

### ImportError: No module named 'PIL'
PIL/Pillow is optional for simulated LCD driver. Install with:
```bash
pip install Pillow
```

### Hardware not detected
Check that:
1. Hardware is properly connected
2. Required libraries are installed (xgolib, spidev, RPi.GPIO)
3. Permissions are correct (may need sudo for GPIO access)
4. Not running in simulation mode (`RIDER_SIMULATOR=0`)

## Development

### Adding a New Driver

1. Create driver file in appropriate directory (e.g., `drivers/sensor/`)
2. Implement physical driver class
3. Create simulated version in `sim.py`
4. Add factory function in `__init__.py`
5. Export via `__all__`
6. Add tests

### Code Style

- Follow existing patterns in `xgo/` and `lcd/`
- Use type hints
- Include docstrings
- Log operations at appropriate levels
- Handle errors gracefully

## License

See project LICENSE file.
