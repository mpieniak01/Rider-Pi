# Rider-Pi Apps — **ARCHITECTURE**

## Goal and General Principles

- **Low Power** and **Stability** — lightweight services, restartable via `systemd`.
- **Single HTTP Entry Point**: public API on port 8080.
- **Internal Communication**: ZMQ PUB/SUB (5555/5556) + files in `data/` and `snapshots/`.
- **Target Environment**: Raspberry Pi (Debian/Bookworm), **Python 3.9**.

---

## Layers and Processes

### 1) HTTP Interface

- `` — REST API (port **8080**).
  - Exposes health (`/healthz`), control (`/api/control`), chat, status, serves assets from `data/`, `snapshots/`.
  - Proxies to internal services via bus (ZMQ) and/or local calls.

### 2) Motion / Web Bridge

- `` (port **8081**) — simplified web interface → motion (optional).
- **Motion Bridge** — the only component with access to **UART** `` (actuator control).
  - Receives commands from the bus (e.g., `motion.move`, `motion.stop`), publishes telemetry `motion.state`.

### 3) Vision / Camera

- **Vision/Camera** — modules in `apps/camera/*` and `apps/vision/*`.
  - Image source (libcamera), detectors (HOG/SSD/TFLite).
  - Results saved to `snapshots/` / `data/` (last frame, raw captures) and publish events (e.g., `vision.person`, `vision.obstacle`).

### 4) Navigator (Autonomous Exploration)

- **Navigator** — autonomous navigation module in `apps/navigator/*`.
  - "Reconnaissance" mode (Stage 1): reactive obstacle avoidance.
  - Subscribes to `vision.obstacle`, publishes on `navigator.state`.
  - Two strategies: STOP (halt) and AVOID (circumvent).
  - API control: `/api/navigator/start`, `/api/navigator/stop`, `/api/navigator/config`.
  - Integration with web interface in `control.html`.
  - See: `docs/modules/navigator.md`

### 4a) Odometry (Position Tracking)

- **Odometry** — robot position tracking module in `apps/odometry/*`.
  - "Reconnaissance" mode (Stage 2): position estimation (x, y, theta) via data fusion.
  - Subscribes to `motion` (movement commands) and `imu.data` (orientation sensor).
  - Publishes `robot.pose` (estimated position and orientation).
  - Uses dead reckoning from movement commands and IMU correction for orientation.
  - Critical component for future stages: mapping (Stage 3) and return to base (Stage 4).
  - See: `docs/modules/odometry.md`

### 4b) Mapper (SLAM Mapping)

- **Mapper** — environment mapping module in `apps/mapper/*`.
  - "Reconnaissance" mode (Stage 3): real-time occupancy grid building.
  - Subscribes to `robot.pose` (from odometry) and `vision.obstacle.data` (from vision with depth estimation).
  - Maintains map in memory as `numpy.array` (inspired by `sim/world.py`).
  - Transforms coordinates: from robot-local → map-global.
  - Marks cells as occupied/free/unknown based on obstacle detection.
  - Fundamental SLAM component — connects perception (vision) with localization (odometry).
  - See: `docs/modules/mapper.md`

### 4c) Vision Depth (Depth Estimation for Mapping)

- **Vision Depth Bridge** — `apps/vision/depth_bridge.py`.
  - Vision system extension with depth estimation for mapping.
  - Monitors navigator state; activates in "Reconnaissance" mode.
  - Converts obstacle detections to (angle, distance) pairs for mapper.
  - Current implementation: simplified estimation (heuristic based on confidence).
  - Future implementation: mono-depth estimation (TFLite model).
  - Publishes `vision.obstacle.data` for mapper consumption.
  - See: `docs/modules/vision.md`

### 5) Voice / Chat

- **Voice** — modular voice architecture in `apps/voice/` supporting two operating modes:
  - **File mode** (`file`): classic pipeline capture→ASR→Chat→TTS→playback
  - **Streaming mode** (`realtime`): duplex WebSocket with partial ASR, streaming chat/TTS
  - **Key Components**:
    - `svc_core.py` — mode selection (file/stream) and delegation to appropriate service
    - `svc_file.py` — file mode implementation
    - `svc_stream_runner.py` — CLI wrappers for streaming mode
    - `stream/svc_streaming.py` — main streaming service (StreamingVoiceService)
    - `stream/transport.py` — WebSocket transport with auto-reconnect
    - `stream/state.py` — PTT (Push-To-Talk) state machine
    - `stream/handlers.py` — WebSocket message/event handling
    - `stream/playout.py` — audio capture and TTS playback
    - `audio/capture.py`, `audio/playback.py` — low-level ALSA/Pulse modules
  - Integration: VAD, KWS, ASR, Chat, TTS; communication via bus (ZMQ) and socket ``
- **Chat** — integration via `/api/chat/*` + state exchange on the bus.

> **Detailed documentation**: `docs/modules/voice.md` — complete description of architecture, configuration, API

### 6) Face

- **UI Face** in `apps/ui/face/*`:
  - **Animator** → **Renderer** (PIL/RAW) → **LCD** (ILI9xx driver).
  - Parameter configuration in `config/face.toml`; custom ENV `FACE_*`.
  - Latest elements: "ribbon" mouth, **arc** eyebrows, pupil drift+clamp, **blink→look coupling**.

---

## Ports and Sockets

| Service / Channel            | Protocol | Port / Path     | Role                                                   |
| ---------------------------- | -------- | --------------- | ------------------------------------------------------ |
| API                          | HTTP     | **8080**        | REST entry point (control/chat/healthz, file serving) |
| Web-Motion Bridge (optional) | HTTP     | **8081**        | Simpler motion interface                               |
| Voice Web API (optional)     | HTTP     | **8092**        | Local TTS/ASR (Piper/Vosk) via HTTP                    |
| ZMQ PUB/SUB                  | ZMQ      | **5555 / 5556** | Internal message bus                                   |
| Voice sock                   | UNIX     | ``              | Voice communication                                    |
| UART                         | Serial   | ``              | Actuator control (exclusively via Motion Bridge)       |

> By default, **no** direct external ports except 8080/8081.

---

## Data Flows (High Level)

```text
[HTTP Client] ──> (8080) API ─┬─> BUS PUB/SUB (5555/5556) ──> Vision/Voice/Motion/Face
                              ├─> local module calls
                              └─> file serving from data/, snapshots/

Vision/Camera ──> snapshots/, data/ (+ events on BUS) ──> API/Clients
Motion Bridge  ──(bus)──> UART /dev/ttyAMA0 ──> actuators
Voice/Chat     ──(bus + sock)──> responses/state ──> API
Face (Animator→Renderer→LCD) ──> preview via API or directly on LCD
```

**BUS (ZMQ)** — example channels:

- `motion` (`motion.move`, `motion.stop`), `motion.state`
- `cmd.balance` — robot stabilization control
- `cmd.height` — height/suspension control
- `vision.face`, `vision.person`, `vision.motion`, `vision.obstacle`
- `vision.obstacle.data` — obstacle data with distance (for mapper, Stage 3)
- `vision.tracking.offset` — tracking offset (Follow Me)
- `tracking.mode:set` — unified tracking mode control (Follow Me: face/hand/none)
- `voice.state`, `voice.kws`, `voice.vad`
- `face.state`, `face.render`
- `events.sentiment`, `events.nlu.emotion` — events for choreographer
- `command.face.expression` — commands to face from choreographer
- `navigator.control`, `navigator.state` — autonomous navigation (Reconnaissance Stage 1 & 4)
- `navigator.map.request`, `mapper.map.data` — map exchange (Stage 4: return to base)
- `navigator.return_home.start` — start return-to-base sequence (Stage 4)
- `robot.pose` — estimated robot position (x, y, theta) from odometry module (Reconnaissance Stage 2)
- `imu.data` — raw IMU sensor data (roll, pitch, yaw) published by motion bridge

---

## Directories and Artifacts

| Directory / file | Purpose                                              |
| ---------------- | ---------------------------------------------------- |
| `apps/`          | Application modules (UI/face, camera, vision, voice…) |
| `services/`      | Service layer (API, bridges, registries)             |
| `web/`           | Frontend / web assets                                |
| `config/`        | Configurations                                       |
| `data/`          | Auxiliary data/latest files (e.g., `last_frame`)     |
| `snapshots/`     | Frame captures / raw shots                           |
| `scripts/`       | Operational, development, diagnostic scripts         |
| `drivers/`       | Hardware drivers (XGO, LCD)                          |
| `tests/`         | Unit/integration tests                               |

### Structure Reorganization History

**PR #10 (2025-01):** Creation of `drivers/` layer
- Moved XGO and LCD drivers from `apps/` to dedicated `drivers/` directory
- Introduced hardware abstraction separating application logic from hardware interfaces
- See: [docs/_pr_summaries/PR10_SUMMARY.md](docs/_pr_summaries/PR10_SUMMARY.md)

**PR #11 (2025-01):** Introduction of simulation mode
- Added simulated driver implementations (`drivers/xgo/sim.py`, `drivers/lcd/sim.py`)
- Introduced driver factories responding to `RIDER_SIMULATOR` variable
- Enabled development and testing without physical hardware access
- See: [docs/_pr_summaries/PR11_SUMMARY.md](docs/_pr_summaries/PR11_SUMMARY.md)

**PR #13 (2025-10):** Operational scripts consolidation
- Merged scripts from `ops/` and `tools/` directories into `scripts/`
- Introduced unified naming convention (prefixes: `sys_`, `diag_`, `dev_`, `demo_`, `util_`)
- See: [docs/_pr_summaries/SCRIPTS_MIGRATION_SUMMARY.md](docs/_pr_summaries/SCRIPTS_MIGRATION_SUMMARY.md), [scripts/README.md](scripts/README.md)

---

## Configuration and Parameters

- **Configuration Sources**:

  1. **ENV** `` — quick parameter tuning (blink, look, drift, coupling, follow).
  2. `` — **lowercase** keys for renderer (e.g., `mouth_y_k`, `brow_y_k`), `FACE_*` aliases for compatibility.
  3. Service parameters (ports, log levels) via `systemd`/ENV.

- **Rule**: API and bridges do **not** access hardware directly (except via specialized drivers). Hardware (UART/LCD) is behind dedicated modules.

---

## Integration Points (Interfaces)

### API (HTTP 8080)

- `/healthz` — overall system health.
- `/api/control` — motion: `{"action":"move|stop|turn", ...}` (validated).
- `/api/chat/*` — conversation / assistance (redirect to voice/chat components).
- `/files/*` — file serving from `data/`, `snapshots/` (latest frames, PNG).

### BUS (ZMQ)

- Internal, namespaces as above. Per-service subscriptions.

### LCD / Render

- `apps/ui/face/driver_ili9xx.py` — bridge to display (RAW/ShowImage).
- `scripts/dev_face-lcd-direct.py` — demo mode (LCD/PNG).

---

## Startup Sequence (Example)

1. `rider-api.service` (HTTP 8080) → ready `/healthz`.
2. ZMQ Broker and subscribers (Vision/Voice/Motion/Face).
3. Vision/Camera (if enabled) → publishes events, saves frames.
4. Motion Bridge → bus listener, access to `/dev/ttyAMA0`.
5. Face → animations on LCD (if device present).

> Services are independent — restart of one should **not** block others.

---

## Responsibility Boundaries and Security

- **Motion Control**: only via Motion Bridge; `action` validation, time and frequency limits.
- **Hardware**: UART and LCD exclusively via dedicated modules.
- **External Access**: via API 8080 (rest locally).
- **Power**: Vision/Camera disabled by default (activated only when needed).

---

## Diagram (Summary)

```text
           +------------------+              +--------------------+
HTTP 8080  |  rider-api       |<--static----|  data/, snapshots/  |
           |  (REST gateway)  |              +--------------------+
           +----+----+--------+
                |    |
                |    +--------------------------+
                |                               \
                v                                v
        +--------------+  PUB/SUB  +------------------+      +-----------------+
        | MotionBridge |<--------->| Vision/Camera    |      | Voice/Chat      |
        | (/dev/tty*)  |           | (detectors, I/O) |      | (sock, TTS/VAD) |
        +--------------+           +------------------+      +-----------------+
                |
                |                               +-------------------------------+
                +------------------------------>| Face (Animator→Renderer→LCD)  |
                                                +-------------------------------+
```

---

## Voice Module — Detailed Architecture

### Module Structure (`apps/voice/`)

The voice module was refactored (PR#1–PR#4, 2024) for simplification and modularization. Current architecture supports two operating modes with flexible transport selection.

#### Operating Modes

1. **File mode (`file`)** — classic pipeline:
   - Capture → WAV file → ASR → Chat (text) → TTS → playback
   - Low resource usage, high compatibility
   - No partial results, full transcription after recording completes

2. **Streaming mode (`realtime`)** — duplex WebSocket:
   - Audio chunks (20ms) → WebSocket → partial ASR + streaming Chat/TTS
   - Barge-in (TTS interruption by new speech)
   - Auto-reconnect with exponential backoff
   - Requires backend supporting realtime (e.g., OpenAI Realtime API)

#### Key Components

**Mode Selection and Delegation:**
- `svc_core.py` — functions `run_listen()`, `run_once()`, `run_ptt()`
  - Analyzes `transport` configuration in `[asr]`, `[chat]`, `[tts]` sections
  - Delegates to `svc_file.py` (file mode) or `svc_stream_runner.py` (realtime mode)

**File Mode:**
- `svc_file.py` — `VoiceService` class, functions `run_listen_file()`, `run_once_file()`
- Uses: `audio/capture.py`, `audio/playback.py`, `asr.py`, `chat.py`, `tts.py`

**Streaming Mode:**
- `svc_stream_runner.py` — CLI wrappers: `run_listen_stream()`, `run_ptt_stream()`, `run_once_stream()`
- `stream/svc_streaming.py` — `StreamingVoiceService` (main service, 700+ lines)
  - Integrates mixins: `StreamHandlersMixin`, `StreamPlayoutMixin`
  - Manages WebSocket lifecycle, audio queues, worker threads
- `stream/transport.py` — `WebSocketTransport`, `ReconnectingTransport`
  - Handles ping/heartbeat, exponential backoff retry
  - Support for `websockets` (async) and `websocket-client` (sync fallback)
- `stream/state.py` — `PTTStateMachine` (Push-To-Talk state machine)
  - States: IDLE, LISTENING, SPEAKING, PROCESSING
  - Events: PTT_START, PTT_STOP, ASR_PARTIAL, TTS_START, TTS_END
- `stream/handlers.py` — `StreamHandlersMixin`
  - WebSocket message handling (ASR partial, TTS audio chunks, session)
  - Keyboard PTT loop, ding sounds
- `stream/playout.py` — `StreamPlayoutMixin`
  - Audio capture thread (sending chunks to WebSocket)
  - TTS player thread (playing incoming audio chunks)
  - Jitter buffer, barge-in handling

**Shared Modules:**
- `audio/capture.py` — audio capture (ALSA/Pulse/command)
- `audio/playback.py` — audio playback (ALSA/Pulse)
- `audio/alsa.py` — ALSA utilities (device list, configuration)
- `asr.py` — ASR abstraction (OpenAI, Vosk)
- `chat.py` — Chat API integration (streaming generator)
- `tts.py` — text-to-speech synthesis (OpenAI, Piper)
- `vad.py` — Voice Activity Detection
- `kws.py` — Keyword Spotting (hotword detection)

**CLI and API:**
- `cli.py` + `cli_commands.py` — command line interface
- `web.py` — HTTP API (Flask): `/asr`, `/tts`, `/capture`, `/healthz`
- `main.py` — main entry point (used by systemd)

### Data Flow

#### File Mode

```text
1. [Hotword/PTT] → trigger capture
2. audio/capture.py → WAV file (silence detection via VAD)
3. asr.py → transcript (text)
4. chat.py → response (text)
5. tts.py → audio file (WAV/MP3)
6. audio/playback.py → speaker output
7. Return to step 1 (in listen mode)
```

**Key Points:**
- One WAV file per capture (optionally saved for debugging)
- ASR only after recording completes (no partial results)
- Chat returns full response (no streaming)
- TTS generates complete audio file before playback

#### Streaming Mode

```text
1. [PTT Start] → WebSocket session.create
2. Capture thread → audio chunks (20ms PCM16) → WebSocket send
3. WebSocket recv → partial ASR transcript → UI update
4. [Silence detection] → audio.commit → final transcription
5. WebSocket recv → streaming Chat response (text) → sentence buffering
6. Sentence complete → TTS start → audio chunks PCM16
7. TTS player thread → audio chunks → jitter buffer → playback
8. [Barge-in] → stop TTS, interrupt playback, new turn (step 2)
9. [PTT Stop] → session cleanup, return to IDLE
```

**Key Points:**
- Duplex audio: simultaneous capture sending and TTS receiving
- Partial ASR published in real-time (UI updates)
- Streaming Chat: response generated as async generator
- Sentence buffering: TTS waits for `.`, `!`, `?` before synthesis
- Barge-in: new speech detection → cancel TTS, clear buffers
- Reconnect: automatic connection resumption after loss (exponential backoff)

### Mode Configuration

Mode selected automatically based on `transport` in configurations:

```toml
[asr]
backend = "openai"
transport = "realtime"    # file | realtime

[chat]
backend = "openai"
transport = "realtime"

[tts]
backend = "openai"
transport = "realtime"
```

If **all** three (`asr`, `chat`, `tts`) have `transport = "realtime"` → streaming mode.
Otherwise → file mode.

> **Note:** In case of mixed configuration (e.g., only one module has `transport = "realtime"`, others `file`), the system falls back to file mode for all services. Partially streaming mode is not supported.

### Refactoring History

**PR#1 (Clean & Freeze):**
- Removed duplicates: `ws_transport.py`, `stream_transport.py`
- Kept `audio/*` for later migration

**PR#2 (CLI Unification):**
- CLI consolidation: removed references to non-existent `cli_new.py`
- One consistent `apps.voice.cli` module

**PR#3 (Tests Migration & Shim Removal):**
- Test migration from legacy shims to new modules
- Removed shims: `svc_stream.py`, `state.py`, `ptt_state.py`, mixins
- New module: `svc_stream_runner.py` (wrappers for CLI)

**PR#4 (WebSocket Transport Consolidation):**
- Removed duplicate `apps/voice/transport.py`
- One transport: `apps/voice/stream/transport.py`

**PR#5 (Documentation):**
- Updated `ARCHITECTURE.md` and `docs/modules/voice.md`
- Consistent description of new architecture

### Removed Files (Legacy)

- `apps/voice/ws_transport.py` (PR#1)
- `apps/voice/stream_transport.py` (PR#1)
- `apps/voice/svc_stream.py` (PR#3)
- `apps/voice/state.py` (PR#3)
- `apps/voice/ptt_state.py` (PR#3)
- `apps/voice/transport.py` (PR#4)

**Migration**: see `docs/modules/voice.md` → "Deprecated / Legacy Files" section

---

## References

- `AGENT.md` — contract and work principles (coding, Done, quality gate).
- `PROJECT.md` — vision, roadmap.
- `config/face.toml` — facial expression tuning.
- `scripts/dev_face-lcd-direct.py` — renderer/LCD demo and diagnostics.
- `tests/` — tests (including pupils, blink, look, clamp).
