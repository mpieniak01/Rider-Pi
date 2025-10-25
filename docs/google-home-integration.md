# Google Home Integration

This document describes the Google Home device control integration in Rider-Pi.

## Overview

The Google Home integration allows you to control smart home devices through the Rider-Pi web interface. The system supports various device types and traits compatible with Google Assistant actions.

## Architecture

The integration consists of three main components:

1. **Backend API** (`services/api_core/google_home_api.py`) - Handles device discovery and command execution
2. **API Routes** (`services/api_server.py`) - Exposes REST endpoints for frontend communication
3. **Web Interface** (`web/home.html`) - Provides user-friendly device control

## API Endpoints

### GET /api/home/devices

Lists all available Google Home devices with their capabilities.

**Response:**
```json
{
  "ok": true,
  "devices": [
    {
      "id": "device_id",
      "name": "Device Name",
      "type": "action.devices.types.LIGHT",
      "traits": ["action.devices.traits.OnOff", "action.devices.traits.Brightness"],
      "state": {
        "on": true,
        "brightness": 80
      },
      "attributes": {
        "colorTemperatureRange": {
          "temperatureMinK": 2000,
          "temperatureMaxK": 6500
        }
      }
    }
  ]
}
```

### POST /api/home/command

Sends a command to a specific device.

**Request:**
```json
{
  "deviceId": "device_id",
  "command": "action.devices.commands.OnOff",
  "params": {
    "on": true
  }
}
```

**Response:**
```json
{
  "ok": true,
  "state": {
    "on": true
  }
}
```

## Supported Device Types

The integration supports the following Google Assistant device types:

### Lights (action.devices.types.LIGHT)

**Supported Traits:**
- `action.devices.traits.OnOff` - Power on/off control
- `action.devices.traits.Brightness` - Brightness adjustment (0-100%)
- `action.devices.traits.ColorSetting` - Color and color temperature control

**UI Controls:**
- Power toggle buttons (On/Off)
- Brightness slider (0-100%)
- Color temperature slider (2000K-6500K)
- RGB color picker

### Thermostats (action.devices.types.THERMOSTAT)

**Supported Traits:**
- `action.devices.traits.TemperatureSetting` - Temperature control and mode setting

**UI Controls:**
- Mode selector (Off, Heat, Cool, Auto)
- Current temperature display
- Target temperature input (°C)

### Vacuums (action.devices.types.VACUUM)

**Supported Traits:**
- `action.devices.traits.StartStop` - Start/stop operation
- `action.devices.traits.Dock` - Return to charging dock

**UI Controls:**
- Start/Stop buttons
- Dock button (return to base)

## Supported Commands and Parameters

### OnOff

**Command:** `action.devices.commands.OnOff`

**Parameters:**
```json
{
  "on": true  // or false
}
```

**Trait Required:** `action.devices.traits.OnOff`

### BrightnessAbsolute

**Command:** `action.devices.commands.BrightnessAbsolute`

**Parameters:**
```json
{
  "brightness": 75  // 0-100
}
```

**Trait Required:** `action.devices.traits.Brightness`

### ColorAbsolute

**Command:** `action.devices.commands.ColorAbsolute`

**Parameters (Color Temperature):**
```json
{
  "color": {
    "temperatureK": 3000  // 2000-6500
  }
}
```

**Parameters (RGB Color):**
```json
{
  "color": {
    "spectrumRgb": 16711680  // 0xRRGGBB (e.g., 0xFF0000 for red)
  }
}
```

**Parameters (HSV Color):**
```json
{
  "color": {
    "spectrumHsv": {
      "hue": 120.0,        // 0-360
      "saturation": 1.0,   // 0-1
      "value": 1.0         // 0-1
    }
  }
}
```

**Trait Required:** `action.devices.traits.ColorSetting`

### ThermostatTemperatureSetpoint

**Command:** `action.devices.commands.ThermostatTemperatureSetpoint`

**Parameters:**
```json
{
  "thermostatTemperatureSetpoint": 21.5  // degrees Celsius
}
```

**Trait Required:** `action.devices.traits.TemperatureSetting`

### ThermostatSetMode

**Command:** `action.devices.commands.ThermostatSetMode`

**Parameters:**
```json
{
  "thermostatMode": "heat"  // "off", "heat", "cool", "auto"
}
```

**Trait Required:** `action.devices.traits.TemperatureSetting`

### StartStop

**Command:** `action.devices.commands.StartStop`

**Parameters:**
```json
{
  "start": true  // true to start, false to stop
}
```

**Trait Required:** `action.devices.traits.StartStop`

### Dock

**Command:** `action.devices.commands.Dock`

**Parameters:**
```json
{}  // No parameters required
```

**Trait Required:** `action.devices.traits.Dock`

## Web Interface

The web interface is accessible at `/home` and provides:

1. **Device List** - Displays all discovered devices in a grid layout
2. **Dynamic Controls** - Shows appropriate controls based on device traits
3. **Real-time Updates** - Auto-refreshes device list every 10 seconds
4. **Activity Log** - Shows command execution history and errors

### UI Features

- **Responsive Design** - Works on desktop and mobile devices
- **Dark Theme** - Matches the Rider-Pi design system
- **i18n Support** - Polish and English translations
- **Status Indicators** - Visual feedback for device states
- **Error Handling** - Clear error messages for failed operations

## Configuration

The Google Home integration uses the following environment variables:

- `GOOGLE_HOME_IP` - IP address of Google Home device (optional)
- `GOOGLE_USERNAME` - Google account username (optional)
- `GOOGLE_PASSWORD` - Google account password (optional)

**Note:** The current implementation includes a mock device database for development and testing. In production, you would need to implement actual Google Home device discovery using libraries like `glocaltokens` and `google-home-local-api`.

## Development Mode

By default, the system runs with mock devices for testing purposes. The mock devices include:

1. **Living Room Light** - Light with OnOff, Brightness, and ColorSetting
2. **Bedroom Thermostat** - Thermostat with TemperatureSetting
3. **Robot Vacuum** - Vacuum with StartStop and Dock

To implement real device control, modify the `get_devices()` and `send_command()` functions in `services/api_core/google_home_api.py`.

## Error Handling

The API returns standard HTTP status codes:

- `200 OK` - Command executed successfully
- `400 Bad Request` - Invalid parameters or unsupported command
- `404 Not Found` - Device not found
- `500 Internal Server Error` - Server error

All responses include an `ok` boolean field and an optional `error` message field.

## Logging

The module uses Python's standard logging facility. Log messages include:

- Device discovery operations
- Command execution details
- Error conditions and exceptions

Logs can be viewed in the system logs or the web interface log panel.

## Future Enhancements

Potential improvements for future versions:

1. **Real Device Discovery** - Implement actual Google Home local API integration
2. **Device Grouping** - Group devices by room or type
3. **Scenes** - Support for activating predefined scenes
4. **Scheduling** - Time-based automation
5. **Voice Control** - Integration with Rider-Pi voice commands
6. **Extended Traits** - Support for additional device traits (locks, fans, etc.)
7. **Persistent Configuration** - Save device preferences

## References

- [Google Assistant Device Types](https://developers.google.com/assistant/smarthome/guides)
- [Google Assistant Device Traits](https://developers.google.com/assistant/smarthome/traits)
- [Google Home Local API](https://github.com/rithvikvibhu/GHLocalApi)
