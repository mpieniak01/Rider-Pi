# Rider-Pi

> This is not an official repository for the Rider-PI robot. It is a sandbox for practicing robot programming.

## Overview

Rider-Pi is a comprehensive robotics platform built on Raspberry Pi, featuring:

- **Autonomous Navigation** - Rekonesans (reconnaissance) mode with obstacle avoidance, SLAM mapping, and return-to-home capability
- **Vision System** - Real-time object detection, face tracking, and depth estimation
- **Voice Interaction** - Voice commands, text-to-speech, and conversational AI integration
- **Expressive Face** - Animated LCD display with emotions and reactions
- **Motion Control** - Quadruped movement with balance and height control
- **Web Interface** - Comprehensive web UI for control and monitoring
- **Modular Architecture** - Event-driven design using ZMQ message bus

## Key Features

### 🤖 Autonomous Navigation (Rekonesans Epic)

Multi-stage autonomous exploration system:

- **Stage 1**: Reactive obstacle avoidance (STOP and AVOID strategies)
- **Stage 2**: Position tracking via odometry (IMU + dead reckoning fusion)
- **Stage 3**: SLAM mapping with occupancy grid
- **Stage 4**: Path planning and return-to-home using A* algorithm

### 👁️ Vision System

- Face and person detection (HOG, TFLite, SSD)
- Follow-me tracking (face and hand tracking)
- Obstacle detection with ROI analysis
- Depth estimation for mapping
- Edge TPU (Coral) acceleration support

### 🗣️ Voice & Chat

- Streaming and file-based voice modes
- ASR (Automatic Speech Recognition)
- Conversational AI (OpenAI, Google Gemini)
- TTS (Text-to-Speech) with multiple backends
- Push-to-Talk (PTT) support
- Keyword spotting and voice activity detection

### 😊 Animated Face

- LCD display with expressive animations
- Emotions: happy, sad, neutral, surprised, angry
- Eye movements and blinking
- Responsive to events and sentiment

### 🕹️ Web Interface

- Live camera preview
- Manual movement controls
- Balance and height adjustment
- Vision tracking controls
- Autonomous navigation dashboard
- Real-time event logging
- Multi-language support (Polish, English)

### 🏗️ Architecture

- **Modular Design**: Independent services communicating via ZMQ message bus
- **Event-Driven**: Publish-subscribe pattern for loose coupling
- **REST API**: Unified HTTP API on port 8080
- **Systemd Integration**: Managed services for reliability
- **Simulation Mode**: Development without hardware

### 🔧 Service Control (App Logic Core)

- Single source of truth for feature orchestration in `apps/app_logic_core` (FeatureManager).
- Systemd operations are wrapped by `common/systemd_ctrl.py`.
- Thin API `/api/logic/feature/<name>` and CLI `scripts/robot_ctl.py start|stop <feature>`.
- Web UI calls the API only; business logic stays in the core layer.

## Quick Start

### Prerequisites

- Raspberry Pi 4 (or compatible)
- Python 3.9+
- XGO quadruped robot (or simulator mode)
- Camera module (optional for vision features)

### Installation

```bash
# Clone repository
git clone https://github.com/mpieniak01/Rider-Pi.git
cd Rider-Pi

# Install dependencies
pip3 install -r requirements-dev.txt

# Initialize configuration files from templates
make config-init

# Configure environment (copy and edit)
cp .env.example .env

# Customize configuration files as needed
nano config/vision.toml      # Vision system paths
nano config/voice_web.toml   # Voice model paths
```

### Running Services

```bash
# Start core services
sudo systemctl start rider-broker      # Message bus
sudo systemctl start rider-api         # REST API server

# Start optional services
sudo systemctl start rider-vision      # Vision system
sudo systemctl start rider-odometry    # Position tracking
sudo systemctl start rider-mapper      # SLAM mapping
sudo systemctl start rider-voice       # Voice interaction

# Start/stop feature stacks via CLI (App Logic Core)
sudo python3 scripts/robot_ctl.py start s3_follow_me_face
sudo python3 scripts/robot_ctl.py stop s4_recon

# Check current scenario state snapshot
sudo python3 scripts/robot_ctl.py status
```

### Web Interface

Open browser: `http://robot-ip:8080/control.html`

## Project Structure

```
Rider-Pi/
├── apps/               # Application modules
│   ├── camera/         # Camera capture
│   ├── chat/           # Chat and NLU
│   ├── mapper/         # SLAM mapping (Stage 3)
│   ├── motion/         # Movement control
│   ├── navigator/      # Autonomous navigation (Stages 1 & 4)
│   ├── odometry/       # Position tracking (Stage 2)
│   ├── ui/             # Face animations
│   ├── vision/         # Vision and detection
│   ├── voice/          # Voice processing
│   └── app_logic_core/ # FeatureManager façade (App Logic Core)
├── services/           # System services
│   ├── api_server.py   # REST API
│   ├── broker.py       # ZMQ message broker
│   ├── api_core/       # API endpoints
│   └── core/           # Core business logic (FeatureManager implementation)
├── common/             # Shared utilities
│   ├── bus.py          # Message bus definitions
│   └── systemd_ctrl.py # Systemd wrapper (start/stop/status)
├── config/            # Configuration files
├── docs/              # Documentation
│   ├── api/           # API documentation
│   ├── apps/          # Application docs
│   ├── modules/       # Module documentation
│   └── ui/            # Web UI documentation
├── drivers/           # Hardware drivers
├── scripts/           # Operational scripts
├── systemd/           # Service definitions
│   ├── legacy/        # Deprecated/legacy units (manual install)
├── tests/             # Test suite
└── web/               # Web interfaces
```

## Documentation

- [Documentation Index](docs/README.md) - Complete documentation index
- [Architecture](ARCHITECTURE.md) - System architecture and design
- [Project Vision](PROJECT.md) - Project goals and roadmap
- [Configuration](docs/CONFIG.md) - Configuration management with TOML templates
- [API Documentation](docs/api-specs/README.md) - REST API endpoints
- [App Logic Core](docs/apps/README.md) - Feature orchestration and FeatureManager
- [Application Modules](docs/apps/) - Detailed module documentation
  - [Navigator](docs/apps/navigator.md) - Autonomous navigation
  - [Odometry](docs/apps/odometry.md) - Position tracking
  - [Mapper](docs/apps/mapper.md) - SLAM mapping
  - [Voice](docs/apps/voice.md) - Voice system
  - [Face](docs/apps/face.md) - Animated face display
- [Web UI Documentation](docs/ui/README.md) - Web interface guides
- [Systemd Services](docs/SYSTEMD_SERVICES_MAPPING.md) - Service mappings
- [Scripts](docs/scripts/README.md) - Operational and development scripts

## Development

### Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run specific module tests
pytest tests/test_navigator.py -v
pytest tests/test_odometry.py -v
pytest tests/test_mapper.py -v

# Skip audio tests (requires ALSA)
ALSA_SKIP_LSOF=1 pytest tests/ -v
```

### Linting

```bash
# Run ruff linter
ruff check --fix

# Format code
ruff format
```

### Simulation Mode

Run without hardware using simulator:

```bash
export RIDER_SIMULATOR=1
python3 -m apps.navigator.main
```

## Contributing

This is a personal learning project. Contributions, suggestions, and feedback are welcome!

## Acknowledgments

- XGO Robot platform
- OpenCV, TensorFlow Lite for vision
- OpenAI, Google Gemini for AI features
- ZMQ for messaging infrastructure

## 📝 License

Distributed under the MIT License. See [`LICENSE`](LICENSE) for more information.

Copyright (c) 2025-2026 Maciej Pieniak
