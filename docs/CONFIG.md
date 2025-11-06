# Configuration Management

## Overview

Rider-Pi uses a centralized configuration system based on TOML files. This document explains how to initialize and manage configuration files.

## Quick Start

### First-time Setup

When setting up Rider-Pi for the first time, initialize the configuration files:

```bash
make config-init
```

This command copies template files (`.toml.example`) to their corresponding `.toml` files in the `config/` directory, but only if the target files don't already exist.

### Configuration Files

The following configuration templates are available:

#### `config/camera.toml.example`

Template for camera module configuration including:
- Snapshot directories and file paths (raw, processed, SSD output)
- Camera source selection (mjpeg, picamera2, v4l2)
- Preview rotation and flip settings
- Frame dimensions

**Example usage:**
```bash
make config-init  # Creates config/camera.toml from template
nano config/camera.toml  # Customize paths and settings
```

#### `config/motion.toml.example`

Template for motion control configuration including:
- Motion bridge serial port configuration (XGO communication)
- Tracking controller PID parameters
- Bus configuration
- Command timing parameters

**Example usage:**
```bash
make config-init  # Creates config/motion.toml from template
nano config/motion.toml  # Customize serial port and tracking parameters
```

#### `config/vision.toml.example`

Template for vision module configuration including:
- Snapshot directories for captured frames
- Data directories for persistent data
- File paths for processed images and detection data
- Vision detector parameters (thresholds, timing)

**Example usage:**
```bash
make config-init  # Creates config/vision.toml from template
nano config/vision.toml  # Customize paths for your environment
```

#### `config/voice_web.toml.example`

Template for voice web server configuration including:
- Piper TTS model paths and settings
- VOSK ASR model directory
- Optional LLM model path
- Web server bind address (host:port)
- ALSA audio device configuration

**Example usage:**
```bash
make config-init  # Creates config/voice_web.toml from template
nano config/voice_web.toml  # Customize model paths and server settings
```

#### `config/face.toml`

Configuration for UI face module including:
- Vendor splash logo path
- LCD rotation for splash screens
- Idle gestures and animations
- Mouth and eye rendering parameters

**Note:** This file uses a hybrid ENV/TOML format for legacy compatibility.

#### `config/jupyter.toml.example`

Template for Jupyter Lab server configuration including:
- Network bind address (IP and port)
- Notebook working directory
- Bash profile to source before startup

**Example usage:**
```bash
make config-init  # Creates config/jupyter.toml from template
nano config/jupyter.toml  # Customize server settings
```

## Configuration File Structure

### Camera Configuration (`camera.toml`)

```toml
[camera]
# Snapshot directory for camera images
snap_dir = "/home/pi/robot/snapshots"

# Snapshot file paths (used by API server)
raw_path = "/home/pi/robot/snapshots/raw.jpg"
proc_path = "/home/pi/robot/snapshots/proc.jpg"
ssd_path = "/home/pi/robot/snapshots/ssd.jpg"

# Source for camera preview (mjpeg, picamera2, v4l2)
source = "mjpeg"

# Preview rotation angle (0, 90, 180, 270)
preview_rot = 270

# Flip settings
preview_flip_h = false
preview_flip_v = false

# Camera frame dimensions
frame_w = 640
frame_h = 480
```

### Motion Configuration (`motion.toml`)

```toml
[motion_bridge]
# Serial port for XGO communication
serial_port = "/dev/ttyAMA0"

[tracking]
# Bus configuration
bus_sub_port = 5556

# PID controller parameters
kp = 0.15
dead_zone = 0.10
timeout_s = 1.0
max_speed = 0.20

# Command parameters
cmd_duration = 0.20
cmd_prio = 50

# Logging
log_level = "INFO"
```

### Vision Configuration (`vision.toml`)

```toml
[paths]
# Snapshot directory for captured frames
snap_dir = "/home/pi/robot/snapshots"

# Data directory for persistent data
data_dir = "/home/pi/robot/data"

# Specific file paths
last_frame = "/home/pi/robot/data/last_frame.jpg"
proc_path = "/home/pi/robot/snapshots/proc.jpg"
raw_path = "/home/pi/robot/snapshots/raw.jpg"
obstacle_json = "/home/pi/robot/data/obstacle.json"
obstacle_annotation = "/home/pi/robot/snapshots/obst_annot.jpg"

[detector]
# Vision detection parameters
min_score = 0.50
on_consecutive = 3
off_ttl_sec = 2.0
```

### Voice Web Configuration (`voice_web.toml`)

```toml
[models]
# Piper TTS model configuration
piper_model = ""  # Full path to .onnx file (overrides piper_model_dir + piper_voice)
piper_model_dir = "/home/pi/robot/models/piper"
piper_voice = "pl_PL-mls-medium.onnx"

# VOSK ASR model directory
vosk_model_dir = "/home/pi/robot/models/vosk/vosk-model-small-pl-0.22"

# Optional LLM model path
llm_model = "models/llm/phi-3-mini-3.8b-instruct.Q4_K_M.gguf"

[server]
# Web server bind address (host:port)
bind = "0.0.0.0:8092"

# ALSA audio device
alsa_device = "plughw:1,0"
```

### Jupyter Configuration (`jupyter.toml`)

```toml
[jupyter]
# Server network configuration
ip = "0.0.0.0"
port = 8888

# Notebook directory
notebook_dir = "/home/pi"

# Bash profile to source before starting
bash_profile = "/home/pi/.bash_profile"
```

## Working with Configuration

### Initialize New Configs

```bash
make config-init
```

This command:
- Scans `config/` for all `*.toml.example` files
- Copies each to `*.toml` if the target doesn't exist
- Skips files that already exist (safe to run multiple times)
- Reports which files were created and which were skipped

### Manual Script Execution

You can also run the initialization script directly:

```bash
bash scripts/config-init.sh
```

### Idempotency

The `config-init` command is idempotent - running it multiple times will not overwrite existing configuration files. This makes it safe to:
- Run after pulling repository updates
- Include in setup/bootstrap scripts
- Use as part of automated deployments

### Version Control

Configuration files generated from templates (`.toml` files) are not tracked in git. Only template files (`.toml.example`) are version controlled. This allows:
- Each deployment to have instance-specific configuration
- Template updates to be shared across all instances
- Local customizations to remain private

## Migration Notes

### From Hardcoded Paths

Previously, many configuration values were hardcoded in Python files:
- `apps/voice/web.py`: `PIPER_MODEL_DIR`, `VOSK_MODEL`
- `apps/vision/*.py`: `SNAP_DIR`, `DATA_DIR`, etc.

**Important:** In this phase (Step 1/2), the Python code still uses the hardcoded values. The configuration templates document the default values that will be used in the next phase when the code is refactored to read from TOML files.

### From robot.env (COMPLETED - Phase 3)

The legacy `robot.env` file and environment-based configuration has been fully replaced by the TOML-based configuration system:
- All Python modules now load configuration from `.toml` files
- systemd services no longer reference `robot.env` 
- Configuration is loaded via module-specific config loaders (e.g., `apps/vision/config.py`, `apps/camera/config.py`, `apps/motion/config.py`)
- Environment variables can still override TOML values when needed
- The `rider-boot-splash.service` handles splash screen display without robot.env dependency

### Systemd Service Configuration Migration (COMPLETED - Current Phase)

All hardcoded configuration values have been migrated from systemd service files to TOML templates:

**rider-api.service**
- Snapshot paths (`SNAP_DIR`, `RAW_PATH`, `PROC_PATH`, `SSD_PATH`) → `config/camera.toml`
- Now loads paths from `apps.camera.config` in `services/api_core/compat.py`

**rider-motion-bridge.service**
- Serial port (`XGO_PORT`) → `config/motion.toml` as `motion_bridge.serial_port`
- Now loads from `apps.motion.config.load_motion_bridge_config()` in `services/motion_bridge.py`

**rider-voice-web.service**
- Bind address (`--bind` argument) → `config/voice_web.toml` as `server.bind`
- Now loads from config in `apps/voice/web.py` main function

**rider-post-splash.service**
- Splash logo path and rotation → `config/face.toml` as `vendor_splash_logo_path` and `splash_lcd_rotate`
- Now loads from `apps.ui.face.config` in `scripts/sys_splash-info.py`

**jupyter.service**
- Server parameters (ip, port, notebook_dir, bash_profile) → `config/jupyter.toml`
- Now uses wrapper script `apps/jupyter_runner.py` to load config and start Jupyter Lab

## Troubleshooting

### Template Not Found

If you create a new `.toml.example` file:
1. Ensure it's in the `config/` directory (root level, not subdirectories)
2. Run `make config-init` to generate the corresponding `.toml` file

### Permission Denied

If you get permission errors:
```bash
chmod +x scripts/config-init.sh
make config-init
```

### Verifying Templates

To check which templates exist:
```bash
ls -la config/*.toml.example
```

To see what would be created:
```bash
bash scripts/config-init.sh
```

## Testing

Unit tests for the configuration initialization system are in `tests/test_config_init.py`:

```bash
# Run all config init tests
pytest tests/test_config_init.py -v

# Run specific test
pytest tests/test_config_init.py::test_config_init_creates_missing_files -v
```

## See Also

- `AGENT.md` - Code review guidelines
- `Makefile` - Build system targets including `config-init`
- `scripts/config-init.sh` - Implementation of config initialization
