# Voice Service Metrics - PR-2

## Overview

PR-2 introduces comprehensive metrics tracking for the voice streaming service. Metrics are available via the `VoiceMetrics` class and can be accessed through the service instance.

## Accessing Metrics

```python
from apps.voice.svc_stream import StreamingVoiceService

# Create service
service = StreamingVoiceService(config=your_config)

# Access metrics object
metrics = service.metrics

# Export as dictionary
metrics_dict = metrics.to_dict()
```

## Available Metrics

### Audio Transmission (TX)
- **audio_bytes_in**: Raw bytes captured from microphone
- **audio_bytes_out**: Bytes sent to WebSocket (base64-encoded)
- **audio_chunks_sent**: Number of audio chunks transmitted
- **audio_chunks_dropped**: Number of chunks dropped due to queue overflow

### Audio Reception (RX)
- **tts_bytes_received**: Bytes received from TTS stream
- **tts_chunks_received**: Number of TTS chunks received

### Response Timing
- **response_rtt_ms**: Round-trip time from commit to response (milliseconds)
- **last_commit_ts**: Timestamp of last audio commit
- **last_response_ts**: Timestamp of last response received

### Connection
- **reconnects**: Number of reconnection attempts
- **connection_duration_s**: Total connection time (seconds)
- **connection_start_ts**: Current connection start time (or None if disconnected)
- **uptime_s**: Total service uptime (seconds)

## Example Usage

```python
# Get metrics snapshot
metrics = service.metrics.to_dict()

print(f"Audio TX: {metrics['audio_bytes_out']} bytes")
print(f"Audio RX: {metrics['tts_bytes_received']} bytes")
print(f"Response RTT: {metrics['response_rtt_ms']}ms")
print(f"Uptime: {metrics['uptime_s']:.1f}s")
```

## Logging Integration

Metrics are automatically tracked during service operation:

```python
# Metrics are updated on key events:
# - service.metrics.on_audio_chunk(bytes_in, bytes_out)
# - service.metrics.on_tts_chunk(bytes_received)
# - service.metrics.on_commit()
# - service.metrics.on_response()
# - service.metrics.on_connect()
# - service.metrics.on_disconnect()
# - service.metrics.on_reconnect()
```

## Monitoring Example

```python
import json
import time

service = StreamingVoiceService(config=config)

# Periodic metrics dump
while service.connected:
    time.sleep(10)
    metrics = service.metrics.to_dict()
    
    # Log to file
    with open('/var/log/voice_metrics.jsonl', 'a') as f:
        f.write(json.dumps(metrics) + '\n')
    
    # Alert on high drop rate
    if metrics['audio_chunks_dropped'] > 100:
        logger.warning(f"High audio drop rate: {metrics['audio_chunks_dropped']}")
```

## Resetting Metrics

```python
# Reset counters (preserves connection state)
service.metrics.reset()
```

## Architecture

The metrics system uses a callback-based architecture:

```
svc_stream.py
    ↓ (tracks events)
VoiceMetrics
    ↓ (exports)
JSON/Dict
```

All metric updates are non-blocking and have minimal performance impact.
