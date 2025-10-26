# Google Home Command API

## Overview

The Google Home Command API enables Rider-Pi to send commands to Google Home and Nest devices through the Smart Device Management (SDM) API. This provides write capabilities, allowing the robot to control smart home devices based on sensors, voice commands, or automation logic.

## Features

- **Device Control**: Send commands to lights, thermostats, switches, and other smart home devices
- **Command Caching**: All command responses are cached locally for debugging and monitoring
- **Error Handling**: Robust error handling with clear error messages (no 500 errors)
- **OAuth Authentication**: Secure authentication using existing Google OAuth credentials
- **UI Integration**: Web interface for manual device control

## API Endpoint

### POST /api/home/command

Send a command to a Google Home device.

**Request:**

```bash
curl -X POST http://127.0.0.1:8080/api/home/command \
  -H "Content-Type: application/json" \
  -d '{
    "deviceId": "enterprises/PROJECT_ID/devices/DEVICE_ID",
    "command": "action.devices.commands.OnOff",
    "params": {"on": true}
  }'
```

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `deviceId` | string | Yes | Full device resource name |
| `command` | string | Yes | SDM command name |
| `params` | object | No | Command parameters |

**Success Response (200 OK):**

```json
{
  "ok": true,
  "result": {
    "status": "SUCCESS"
  }
}
```

**Error Response (401/500):**

```json
{
  "ok": false,
  "error": "Not authenticated"
}
```

## Common Commands

### OnOff - Control Power

Turn devices on or off.

```bash
# Turn on
curl -X POST http://127.0.0.1:8080/api/home/command \
  -H "Content-Type: application/json" \
  -d '{
    "deviceId": "enterprises/PROJECT_ID/devices/DEVICE_ID",
    "command": "action.devices.commands.OnOff",
    "params": {"on": true}
  }'

# Turn off
curl -X POST http://127.0.0.1:8080/api/home/command \
  -H "Content-Type: application/json" \
  -d '{
    "deviceId": "enterprises/PROJECT_ID/devices/DEVICE_ID",
    "command": "action.devices.commands.OnOff",
    "params": {"on": false}
  }'
```

### BrightnessAbsolute - Set Brightness

Set brightness level (0-100).

```bash
curl -X POST http://127.0.0.1:8080/api/home/command \
  -H "Content-Type: application/json" \
  -d '{
    "deviceId": "enterprises/PROJECT_ID/devices/DEVICE_ID",
    "command": "action.devices.commands.BrightnessAbsolute",
    "params": {"brightness": 75}
  }'
```

### ColorAbsolute - Set Color

Set color temperature (in Kelvin) or RGB value.

```bash
# Color temperature
curl -X POST http://127.0.0.1:8080/api/home/command \
  -H "Content-Type: application/json" \
  -d '{
    "deviceId": "enterprises/PROJECT_ID/devices/DEVICE_ID",
    "command": "action.devices.commands.ColorAbsolute",
    "params": {"color": {"temperatureK": 3000}}
  }'

# RGB color
curl -X POST http://127.0.0.1:8080/api/home/command \
  -H "Content-Type: application/json" \
  -d '{
    "deviceId": "enterprises/PROJECT_ID/devices/DEVICE_ID",
    "command": "action.devices.commands.ColorAbsolute",
    "params": {"color": {"spectrumRgb": 16711680}}
  }'
```

### ThermostatTemperatureSetpoint - Set Temperature

Set thermostat target temperature (in Celsius).

```bash
curl -X POST http://127.0.0.1:8080/api/home/command \
  -H "Content-Type: application/json" \
  -d '{
    "deviceId": "enterprises/PROJECT_ID/devices/DEVICE_ID",
    "command": "action.devices.commands.ThermostatTemperatureSetpoint",
    "params": {"thermostatTemperatureSetpoint": 20.5}
  }'
```

### ThermostatSetMode - Set Thermostat Mode

Set thermostat operating mode.

```bash
curl -X POST http://127.0.0.1:8080/api/home/command \
  -H "Content-Type: application/json" \
  -d '{
    "deviceId": "enterprises/PROJECT_ID/devices/DEVICE_ID",
    "command": "action.devices.commands.ThermostatSetMode",
    "params": {"thermostatMode": "heat"}
  }'
```

Available modes: `off`, `heat`, `cool`, `heatcool`, `eco`

## Command Cache

All command responses are cached in `~/robot/data/google/last_command.json` for debugging and monitoring.

**Cache Structure:**

```json
{
  "timestamp": 1698765432.123,
  "device_id": "enterprises/PROJECT_ID/devices/DEVICE_ID",
  "command": "action.devices.commands.OnOff",
  "params": {"on": true},
  "ok": true,
  "response": {"status": "SUCCESS"},
  "error": null
}
```

**View Cache:**

```bash
cat ~/robot/data/google/last_command.json | jq
```

## Configuration

The command API uses the same authentication configuration as the Google Home feed:

| Environment Variable | Required | Description |
|---------------------|----------|-------------|
| `GOOGLE_CLIENT_ID` | Yes | OAuth 2.0 Client ID |
| `GOOGLE_CLIENT_SECRET` | Yes | OAuth 2.0 Client Secret |
| `GOOGLE_PROJECT_ID` | Yes | SDM API Project ID |
| `DATA_DIR` | No | Data directory (default: `~/robot/data`) |

**Token Storage:**

Refresh tokens are stored in: `config/local/google_tokens.json`

## Error Handling

The API never returns HTTP 500 errors. All errors are returned as controlled JSON responses:

| Error | HTTP Status | Description |
|-------|-------------|-------------|
| Not authenticated | 401 | No valid OAuth tokens available |
| Missing parameters | 400 | Missing `deviceId` or `command` |
| Command failed | 500 | API call succeeded but command failed |

**Error Response Example:**

```json
{
  "ok": false,
  "error": "Not authenticated"
}
```

## Security

- **Local Access Only**: Commands are only accepted from `127.0.0.1:8080`
- **No Token Exposure**: Tokens are never logged or exposed in UI
- **Secure Storage**: Refresh tokens stored in protected config directory
- **Rate Limiting**: Recommended 1 request/second per device (implement in application layer)

## Web UI

Control devices through the web interface at:

```
http://127.0.0.1:8080/web/google_home.html
```

**Features:**

- Visual device list with current states
- On/Off buttons with status feedback
- Brightness, color, and temperature controls
- Real-time success/error notifications
- Green ✅ for success, Red ❌ for errors

## Testing

Run tests:

```bash
# All Google command tests
pytest tests/test_google_command.py -v

# Specific test
pytest tests/test_google_command.py::TestGoogleCommandAPI::test_command_endpoint_success -v
```

## Troubleshooting

### Authentication Failed

```bash
# Check authentication status
curl http://127.0.0.1:8080/api/home/status

# Re-authenticate
curl -X POST http://127.0.0.1:8080/api/home/auth
```

### Command Failed

```bash
# Check last command cache
cat ~/robot/data/google/last_command.json | jq

# Check device list
curl http://127.0.0.1:8080/api/home/devices | jq
```

### Logs

```bash
# API server logs
journalctl -u rider-api -f

# Google bridge logs (if using systemd service)
journalctl -u rider-google-bridge -f
```

## Future Enhancements

- Local Home SDK integration for faster local control
- Matter protocol support
- Custom macros and automation rules
- Sensor-triggered actions
- Voice command integration

## References

- [Google Smart Device Management API](https://developers.google.com/nest/device-access/api)
- [Device Access Console](https://console.nest.google.com/device-access/)
- [OAuth 2.0 Setup](https://developers.google.com/identity/protocols/oauth2)
