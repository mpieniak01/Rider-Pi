# Rider-Pi REST API Documentation

This directory contains documentation for the Rider-Pi REST API endpoints.

## API Server

The API server runs on port **8080** and provides REST endpoints for controlling the robot and accessing system information.

**Service:** `rider-api.service`  
**Entry point:** `services/api_server.py`  
**Base URL:** `http://robot-ip:8080`

## Available Endpoints

### Core APIs
- [Control API](control.md) - Robot movement and control
- [Navigator API](navigator.md) - Autonomous navigation (Rekonesans mode)

<!-- The following API documentation files are planned for future documentation: -->
<!-- - [Camera API](camera.md) - Camera access and vision system -->
<!-- - [Chat API](chat.md) - Voice and text chat interface -->
<!-- - [Face API](face.md) - Robot face animation control -->
<!-- - [Google Home API](google-home.md) - Google Home integration -->

### Health and Status
- `GET /healthz` - System health check
- `GET /api/status` - Detailed system status
- `GET /api/app-metrics` - Application metrics (OK/Error counts for interactive APIs)

## Application Metrics

### GET /api/app-metrics

Returns metrics for interactive API endpoints, tracking successful (OK) and failed (Error) requests.

**No authentication required.**

**Request:**
```bash
GET /api/app-metrics
```

**Response:**
```json
{
  "ok": true,
  "metrics": {
    "control": {
      "ok": 42,
      "error": 3
    },
    "navigator": {
      "ok": 15,
      "error": 0
    },
    "voice": {
      "ok": 28,
      "error": 2
    },
    "google_home": {
      "ok": 10,
      "error": 1
    },
    "chat": {
      "ok": 5,
      "error": 0
    },
    "face": {
      "ok": 12,
      "error": 0
    }
  },
  "total_errors": 6
}
```

**Monitored API Groups:**

- **Control:** `/api/control`, `/api/cmd`, `/api/control/balance`, `/api/control/height`
- **Navigator:** `/api/navigator/start`, `/api/navigator/stop`, `/api/navigator/config`, `/api/navigator/return_home`
- **Voice:** `/api/voice/capture`, `/api/voice/say`, `/api/voice/tts`, `/api/voice/asr`
- **GoogleHome:** `/api/home/command`
- **Chat:** `/api/chat/send`
- **Face:** `/face/render`, `/face/play`, `/face/stop`, `/api/draw/face`

**Note:** System endpoints (health checks, status queries, camera streams, etc.) are **not** counted in these metrics. Only user-initiated interactive actions are tracked.

**Displayed on:** Main dashboard at `/view` in the "API Metrics" card.

## Common Patterns

### CORS Support
All API endpoints support CORS (Cross-Origin Resource Sharing) and respond to OPTIONS preflight requests.

### Response Format
Most endpoints return JSON responses:

```json
{
  "ok": true,
  "data": { ... }
}
```

Error responses:

```json
{
  "ok": false,
  "error": "Error message"
}
```

### Timestamps
All events and commands include a `ts` (timestamp) field in Unix epoch format (seconds since 1970-01-01).

## Static File Serving

The API server also serves static files:

- `/` - Serves files from `web/` directory
- `/camera/last` - Last captured camera frame
- `/files/*` - Files from `data/` and `snapshots/`

## Integration with Bus

Many API endpoints publish commands to the internal ZMQ message bus. See `common/bus.py` for topic definitions and payload formats.

## See Also

- [ARCHITECTURE.md](../../ARCHITECTURE.md) - Overall system architecture
- [common/bus.py](../../common/bus.py) - Bus topic definitions
- [services/api_server.py](../../services/api_server.py) - API server implementation
