# AI Mode Integration Examples

This directory contains example code demonstrating how different modules should integrate with the AI Mode switching system.

## Overview

The AI Mode system allows the robot to switch between two operating modes:

- **Local Mode** (`local`): All AI processing (Vision, Voice, NLU) runs locally on the Raspberry Pi
- **PC Offload Mode** (`pc_offload`): Heavy AI processing is offloaded to a more powerful PC via ZMQ

## API Usage

### Checking Current Mode

```python
from common import ai_mode

# Check if in offload mode
if ai_mode.is_offload():
    print("Using PC for heavy processing")

# Check if in local mode
if ai_mode.is_local():
    print("Using local processing")

# Get current mode as string
mode = ai_mode.get_mode()  # Returns "local" or "pc_offload"

# Get mode with timestamp
info = ai_mode.get_mode_info()
# Returns: {"mode": "local", "changed_ts": 1234567890.123}
```

### Reacting to Mode Changes

```python
from common.bus import BusSub, TOPIC_SYSTEM_AI_MODE_CHANGED

# Subscribe to mode change events
mode_sub = BusSub(TOPIC_SYSTEM_AI_MODE_CHANGED)

while True:
    topic, payload = mode_sub.recv(timeout_ms=100)
    if topic and payload:
        new_mode = payload.get("mode")
        print(f"AI mode changed to: {new_mode}")
        # React to the change...
```

## Example Files

### 1. Vision Module (`vision_ai_mode_example.py`)

Demonstrates how vision processing should adapt:
- **Local Mode**: Run local detectors (TFLite, HOG, etc.)
- **PC Offload Mode**: Subscribe to `TOPIC_VISION_OBSTACLE_ENHANCED` for PC-processed results

Key topics:
- Subscribe to: `system.ai.mode.changed`, `vision.obstacle.enhanced`
- Publish to: `vision.obstacle`, `vision.obstacle.enhanced` (forwarded)

### 2. Voice Module (`voice_ai_mode_example.py`)

Demonstrates how voice processing should adapt:
- **Local Mode**: Run local ASR/TTS/NLU (Vosk, Piper, etc.)
- **PC Offload Mode**: Send raw audio to PC, receive processed results

Key topics:
- Subscribe to: `system.ai.mode.changed`, `voice.command` (from PC)
- Publish to: `voice.audio.raw` (to PC), `voice.transcript`, `voice.intent`

### 3. Navigator Module (`navigator_ai_mode_example.py`)

Demonstrates how navigation should adapt:
- **Local Mode**: Use local obstacle detection only
- **PC Offload Mode**: Prefer enhanced obstacle data from PC (with local fallback)

Key topics:
- Subscribe to: `vision.obstacle`, `vision.obstacle.enhanced`
- Merges or prioritizes data based on current mode

## ZMQ Topics Reference

### System Topics

- `system.ai.mode.changed`: Published when AI mode changes
  - Payload: `{"mode": "local"|"pc_offload", "changed_ts": float, "ts": float}`

### Vision Topics

- `vision.obstacle`: Local obstacle detection results
  - Payload: `{"present": bool, "confidence": float, "ts": float}`
- `vision.obstacle.enhanced`: Enhanced obstacle data from PC
  - Payload: `{"obstacles": [...], "enhanced": bool, "ts": float}`

### Voice Topics

- `voice.audio.raw`: Raw audio data sent to PC for processing
  - Payload: `{"audio_data": "base64_encoded", "ts": float}`
- `voice.transcript`: Transcribed text (local or from PC)
  - Payload: `{"text": str, "ts": float}`
- `voice.intent`: Extracted intent (local or from PC)
  - Payload: `{"action": str, "params": {...}, "ts": float}`

## Testing

Run the examples to see how modules adapt to mode changes:

```bash
# Terminal 1: Run vision example
python3 examples/vision_ai_mode_example.py

# Terminal 2: Run voice example
python3 examples/voice_ai_mode_example.py

# Terminal 3: Run navigator example
python3 examples/navigator_ai_mode_example.py

# Terminal 4: Change AI mode via API
curl -X PUT http://localhost:8080/api/system/ai-mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "pc_offload"}'

# Or switch back to local
curl -X PUT http://localhost:8080/api/system/ai-mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "local"}'
```

## Integration Guidelines

When adapting a module to support AI mode:

1. **Check mode at startup**: Determine initial behavior
2. **Subscribe to mode changes**: React dynamically to changes
3. **Handle both modes**: Gracefully switch between local and offload
4. **Maintain fallback**: If PC offload fails, fall back to local processing
5. **Clean up resources**: Release local models when switching to offload
6. **Lazy initialization**: Load heavy models only when needed

## Web Interface

Control AI mode via the web interface at:
- http://localhost:8080/control

The interface provides:
- Current mode display with status indicator
- Toggle buttons to switch between modes
- Timestamp of last mode change
- Real-time status updates

## API Endpoints

### GET /api/system/ai-mode

Get current AI mode and last change timestamp.

**Response:**
```json
{
  "ok": true,
  "mode": "local",
  "changed_ts": 1234567890.123
}
```

### PUT /api/system/ai-mode

Change AI mode. Publishes `system.ai.mode.changed` event on ZMQ bus.

**Request:**
```json
{
  "mode": "local"
}
```

**Response:**
```json
{
  "ok": true,
  "mode": "local",
  "changed_ts": 1234567890.456
}
```

## Configuration

Default mode is set in `config/system.toml`:

```toml
[ai]
default_mode = "local"  # or "pc_offload"
```

State is persisted to `$DATA_DIR/ai_mode_state.toml` for persistence across reboots.
