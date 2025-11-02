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
- [Camera API](camera.md) - Camera access and vision system
- [Chat API](chat.md) - Voice and text chat interface
- [Face API](face.md) - Robot face animation control
- [Google Home API](google-home.md) - Google Home integration

### Health and Status
- `GET /healthz` - System health check
- `GET /api/status` - Detailed system status

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
