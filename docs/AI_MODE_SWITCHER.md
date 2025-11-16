# AI Mode Switcher Feature

## Overview

The AI Mode Switcher is a global control mechanism that allows dynamic switching between two processing modes for AI-intensive tasks:

- **`local`** - All AI processing (ASR, NLU, Vision Detection) runs on the Rider-Pi device
- **`pc_offload`** - AI-intensive tasks are offloaded to a PC via ZMQ for processing

## Architecture

### Core Components

1. **Configuration Module** (`common/ai_mode.py`)
   - Thread-safe mode management
   - Environment variable support (`RIDER_AI_MODE`)
   - Runtime mode switching with timestamp tracking

2. **REST API** (`services/api_core/ai_mode_api.py`)
   - `GET /api/system/ai-mode` - Query current mode
   - `PUT /api/system/ai-mode` - Change mode
   - ZMQ event publishing on mode changes

3. **Service Adapters**
   - `apps/vision/ai_mode_adapter.py` - Vision service integration
   - `apps/voice/ai_mode_adapter.py` - Voice service integration
   - `apps/navigator/ai_mode_adapter.py` - Navigator service integration

4. **Web UI** (`web/control.html`)
   - Visual mode indicator
   - Toggle buttons for mode switching
   - Real-time status updates

### Configuration Files

- `config/system.toml` - System-wide AI mode setting
- `config/voice.toml` - Voice service AI mode configuration
- `config/vision.toml.example` - Vision service AI mode configuration

## Usage

### Environment Variable

Set the initial AI mode via environment variable:

```bash
export RIDER_AI_MODE=local      # Use local processing (default)
export RIDER_AI_MODE=pc_offload # Offload to PC
```

### API Endpoints

#### Get Current Mode

```bash
curl http://robot-ip:8080/api/system/ai-mode
```

Response:
```json
{
  "mode": "local",
  "changed_ts": 1699999999.123
}
```

#### Change Mode

```bash
curl -X PUT http://robot-ip:8080/api/system/ai-mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "pc_offload"}'
```

Response:
```json
{
  "mode": "pc_offload",
  "changed": true,
  "changed_ts": 1700000000.456
}
```

### Python API

#### In Service Code

```python
from common.ai_mode import get_mode, is_local, is_offload

# Check current mode
current_mode = get_mode()  # Returns "local" or "pc_offload"

# Quick checks
if is_local():
    # Use local processing
    pass

if is_offload():
    # Offload to PC
    pass
```

#### Using Service Adapters

**Vision Service:**
```python
from apps.vision.ai_mode_adapter import (
    should_run_local_detectors,
    should_publish_frames_to_pc
)

if should_run_local_detectors():
    # Activate HOG, TFLite detectors
    pass

if should_publish_frames_to_pc():
    # Publish frames to PC via ZMQ
    pass
```

**Voice Service:**
```python
from apps.voice.ai_mode_adapter import (
    should_run_local_asr,
    should_run_local_tts,
    should_run_local_nlu,
    should_offload_to_pc
)

if should_run_local_asr():
    # Use local ASR engine
    pass

if should_offload_to_pc():
    # Send audio to PC for processing
    pass
```

**Navigator Service:**
```python
from apps.navigator.ai_mode_adapter import (
    should_use_local_obstacle_data,
    should_use_pc_enhanced_data
)

if should_use_local_obstacle_data():
    # Subscribe to local obstacle detection
    pass

if should_use_pc_enhanced_data():
    # Subscribe to vision.obstacle.enhanced from PC
    pass
```

## ZMQ Events

When the AI mode changes, a ZMQ event is published:

**Topic:** `system.ai.mode.changed` (constant: `TOPIC_SYSTEM_AI_MODE_CHANGED`)

**Payload:**
```json
{
  "mode": "pc_offload",
  "ts": 1700000000.456
}
```

Services can subscribe to this topic to react to mode changes in real-time:

```python
from common.bus import BusSub, TOPIC_SYSTEM_AI_MODE_CHANGED

sub = BusSub(TOPIC_SYSTEM_AI_MODE_CHANGED)
while True:
    topic, payload = sub.recv()
    if topic == TOPIC_SYSTEM_AI_MODE_CHANGED:
        new_mode = payload.get("mode")
        # React to mode change
        handle_mode_change(new_mode)
```

## Web UI Integration

The AI mode switcher is integrated into the control panel at `http://robot-ip:8080/control.html`.

**Features:**
- Visual status badge showing current mode (🖥️ Local or 💻 PC Offload)
- Toggle buttons to switch between modes
- Timestamp showing when mode was last changed
- Real-time updates every 3 seconds

**UI Elements:**
- Green badge = Local mode active
- Yellow badge = PC Offload mode active
- Disabled button = Currently active mode

## Implementation Details

### Thread Safety

The AI mode module uses `threading.RLock()` to ensure thread-safe mode changes:

```python
with _mode_lock:
    _current_mode = mode
    _mode_changed_ts = time.time()
```

### Fallback Behavior

Service adapters include fallback logic if the AI mode module is unavailable:

```python
try:
    from common.ai_mode import get_mode
except ImportError:
    def get_mode():
        return "local"  # Safe default
```

### Error Handling

The API endpoint validates mode values and returns appropriate HTTP status codes:

- `200 OK` - Mode successfully retrieved or changed
- `400 Bad Request` - Invalid mode value or missing parameter
- `405 Method Not Allowed` - Unsupported HTTP method

Security: Error messages do not expose internal stack traces.

## Testing

### Unit Tests

```bash
# Test core AI mode functionality
pytest tests/test_ai_mode.py -v

# Test service adapters
pytest tests/test_ai_mode_adapters.py -v

# Test API integration
pytest tests/test_ai_mode_integration.py -v
```

**Test Coverage:**
- Mode initialization and switching (15 tests)
- Service adapters for all services (9 tests)
- API endpoint integration (3 tests)
- Thread safety validation
- ZMQ event publishing

### Manual Testing

1. **Web UI Test:**
   ```bash
   # Start API server
   python -m services.api_server
   
   # Open browser to http://localhost:8080/control.html
   # Click "Local" and "PC Offload" buttons
   # Verify status badge updates
   ```

2. **API Test:**
   ```bash
   # Query current mode
   curl http://localhost:8080/api/system/ai-mode
   
   # Change to PC offload
   curl -X PUT http://localhost:8080/api/system/ai-mode \
     -H "Content-Type: application/json" \
     -d '{"mode": "pc_offload"}'
   
   # Verify change
   curl http://localhost:8080/api/system/ai-mode
   ```

3. **ZMQ Event Test:**
   ```bash
   # In one terminal, subscribe to events
   python -c "from common.bus import BusSub; \
              s = BusSub('system.ai.mode.changed'); \
              print(s.recv())"
   
   # In another terminal, change mode
   curl -X PUT http://localhost:8080/api/system/ai-mode \
     -H "Content-Type: application/json" \
     -d '{"mode": "local"}'
   ```

## Security

### Security Scan Results

**CodeQL Analysis:** ✅ No vulnerabilities found

**Fixed Issues:**
- Stack trace exposure in error responses (py/stack-trace-exposure)
  - Changed from exposing exception details to generic error messages

### Security Best Practices

1. **Input Validation:** Mode values are validated before processing
2. **Error Handling:** Generic error messages prevent information leakage
3. **Thread Safety:** Lock-protected mode changes prevent race conditions
4. **CORS Headers:** Properly configured for cross-origin requests

## Performance

### Overhead

- **Mode Query:** < 1ms (simple in-memory variable access)
- **Mode Change:** < 1ms + ZMQ publish overhead (~1-5ms)
- **Web UI Polling:** Every 3 seconds (minimal network overhead)

### Scalability

- Thread-safe implementation supports concurrent access
- ZMQ event-based architecture supports multiple subscribers
- No database or file I/O required for mode operations

## Future Enhancements

### Potential Improvements

1. **Automatic Mode Switching:**
   - CPU/Memory threshold-based switching
   - Network latency-based switching
   - Battery level-based switching

2. **Per-Service Mode Control:**
   - Different modes for different services
   - Vision: local, Voice: pc_offload, etc.

3. **Mode History:**
   - Track mode changes over time
   - Analytics and reporting

4. **PC Connection Health:**
   - Monitor PC availability
   - Auto-fallback to local on PC disconnect

5. **Configuration Profiles:**
   - Predefined mode configurations
   - Quick switching between profiles

## Troubleshooting

### Common Issues

**Issue:** Mode doesn't change
- Check API server logs for errors
- Verify JSON payload format
- Check CORS configuration

**Issue:** Web UI shows "Error"
- Verify API server is running
- Check network connectivity
- Inspect browser console for JavaScript errors

**Issue:** Services not responding to mode change
- Verify service has imported ai_mode_adapter
- Check service logs for mode detection messages
- Ensure ZMQ bus is running

**Issue:** ZMQ events not received
- Verify ZMQ broker is running
- Check subscriber topic matches exactly
- Validate ZMQ endpoint configuration

## Provider Registry Integration

The new Provider Registry (see [OFFLOAD_PROVIDER_PROTOCOL.md](OFFLOAD_PROVIDER_PROTOCOL.md)) builds on top of the AI mode primitives described here:

- The registry keeps provider selection per domain (`vision`, `voice`, `text`) and, whenever a domain switches to `pc`, it emits the same `system.ai.mode.changed` events that existing services already consume.
- Legacy services that only understand the global AI mode continue to operate, because the registry can keep `mode="local"` for incompatible domains while still offloading others.
- On Rider-PC failure the registry forces `mode="local"` and publishes change events so detectors resume automatically.

No code changes are required inside `common/ai_mode.py`; the registry simply orchestrates per-domain routing and enriches UI/PC telemetry.

## Support

For issues or questions:
1. Check service logs for diagnostic messages
2. Run diagnostic commands to verify mode
3. Review test cases for usage examples
4. Consult API documentation for endpoint details

## License

This feature is part of the Rider-Pi project and follows the same license terms.
