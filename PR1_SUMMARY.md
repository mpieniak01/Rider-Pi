# PR-1 Refactoring Summary

## Overview
This PR extracts protocol and transport utilities from `svc_stream.py` and `stream_chunks.py` into dedicated modules, improving code organization without changing functionality.

## Changes Made

### 1. Created `apps/voice/rt_protocol.py` (306 lines)
**Purpose:** Realtime API protocol message builders and validators

**Exports:**
- `RealtimeMessageType` - Message type constants
- `build_session_update()` - Build session.update with input_audio_format object
- `build_audio_append()` - Build input_audio_buffer.append
- `build_audio_commit()` - Build input_audio_buffer.commit
- `build_audio_clear()` - Build input_audio_buffer.clear
- `build_response_create()` - Build response.create
- `build_response_cancel()` - Build response.cancel for barge-in
- `decode_audio_from_message()` - Decode base64 audio from WebSocket messages
- `parse_message_type()` - Parse message type from JSON
- `is_session_event()`, `is_response_event()`, `is_error_event()` - Type checkers

**Key Features:**
- Centralized protocol layer for OpenAI Realtime API
- Proper input_audio_format object structure (pcm16, sample_rate_hz, channels)
- Server VAD configuration support
- Temperature and modality configuration

### 2. Created `apps/voice/ws_transport.py` (289 lines)
**Purpose:** WebSocket transport utilities and helpers

**Exports:**
- `WebSocketConfig` - WebSocket connection configuration
- `RetryConfig` - Retry and backoff configuration
- `QueueConfig` - Queue limits and backpressure configuration
- `ConnectionMetrics` - Connection metrics tracking
- `BoundedQueue` - Async queue with drop-on-full policy
- `calculate_backoff_delay()` - Exponential backoff calculation
- `should_retry()` - Retry decision logic
- `env_int()`, `env_flag()`, `env_float()` - Environment variable helpers

**Key Features:**
- Queue management with backpressure control
- Exponential backoff for retries (default: 250ms base, 5s max)
- Connection metrics (bytes sent/received, messages, drops, reconnects)
- Drop-on-full queue policy to prevent blocking

### 3. Updated `apps/voice/stream_chunks.py` (164 lines, -34 lines)
**Changes:**
- Delegates all message building to `rt_protocol.py`
- Maintains backward compatibility with existing API
- Removed duplicate message builder code
- Updated imports to use rt_protocol functions

**Impact:**
- Cleaner separation of concerns
- Less duplicate code
- Easier to maintain protocol changes in one place

### 4. Updated `apps/voice/svc_stream.py` (1350 lines, -9 lines)
**Changes:**
- Import `build_response_cancel` from rt_protocol
- Use rt_protocol builder for response.cancel
- Fixed `__del__` method to avoid unawaited coroutine warnings
- No changes to public API or CLI interface

**Impact:**
- Cleaner code with better separation
- No functional changes
- Fixed test warnings

### 5. Updated `tests/test_voice_ws_close.py`
**Changes:**
- Use `@pytest_asyncio.fixture` for async fixtures
- Add proper cleanup with `yield` and `await svc.close()`
- Fix `test_stop_with_running_loop` to actually await coroutines in mock
- Eliminates "coroutine 'aclose' was never awaited" warning

## Testing Results

### Unit Tests
- ✅ 90/91 voice tests pass (1 pre-existing failure unrelated to changes)
- ✅ All new tests pass
- ✅ No coroutine warnings
- ✅ ruff check passes
- ✅ ruff format passes

### Integration Tests
- ✅ StreamingVoiceService creates successfully
- ✅ AudioChunkProcessor uses rt_protocol builders
- ✅ All message builders produce correct JSON
- ✅ Protocol messages have correct structure

### Manual Verification
```python
# session.update with proper format
build_session_update(
    voice='alloy',
    input_sample_rate=16000,
    server_vad=True
)
# → {"type": "session.update", "session": {"input_audio_format": {"type": "pcm16", "sample_rate_hz": 16000, "channels": 1}, ...}}

# Retry backoff works correctly
RetryConfig(max_retries=5, base_delay_ms=100, max_delay_ms=2000)
# → Delays: 0.1s, 0.2s, 0.4s, 0.8s, 1.6s, 2.0s

# BoundedQueue drops oldest on overflow
queue = BoundedQueue(maxsize=3, drop_on_full=True)
# → When full, new items replace oldest
```

## Compliance

### Ruff
- ✅ Line length ≤ 120 characters
- ✅ No linting errors
- ✅ Properly formatted

### File Sizes
- ✅ rt_protocol.py: 306 lines (well under 600)
- ✅ ws_transport.py: 289 lines (well under 600)
- ✅ stream_chunks.py: 164 lines (reduced from 198)

### Compatibility
- ✅ No changes to public API
- ✅ No changes to CLI commands
- ✅ No changes to TOML configuration
- ✅ All event logging preserved
- ✅ Backward compatible

## Migration Notes

### For Future PRs
- Use `rt_protocol` builders for all Realtime API messages
- Use `ws_transport.BoundedQueue` for queue management with backpressure
- Use `ws_transport.ConnectionMetrics` for tracking connection stats
- Use `ws_transport.calculate_backoff_delay()` for retry logic

### Example Usage
```python
from apps.voice.rt_protocol import build_session_update, build_audio_commit
from apps.voice.ws_transport import BoundedQueue, ConnectionMetrics

# Build messages
session_msg = build_session_update(voice='alloy', input_sample_rate=16000)
commit_msg = build_audio_commit()

# Queue with backpressure
tx_queue = BoundedQueue(maxsize=100, drop_on_full=True)

# Track metrics
metrics = ConnectionMetrics()
metrics.record_connect()
metrics.record_send(len(session_msg))
```

## Next Steps (PR-2)
- Extract PTT state management to `ptt_state.py`
- Extract audio TX/RX to separate modules
- Add voice metrics module
- Further reduce svc_stream.py size
