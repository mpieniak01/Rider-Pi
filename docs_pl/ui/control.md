# control.html - Main Control Interface

The main web interface for controlling the Rider-Pi robot.

**URL:** `http://robot-ip:8080/control.html`

## Overview

The control interface provides a comprehensive dashboard for:
- Live camera preview
- Manual robot movement
- Balance and height control
- Vision tracking (Follow Me feature)
- Autonomous navigation (Rekonesans mode)
- Real-time event logging

---

## Interface Sections

### 1. Camera Preview
**Location:** Top of page

**Features:**
- Live camera feed with auto-refresh
- Toggle between camera (`/camera/last`) and edge detection (`/vision/edge`)
- Auto-refresh control (on/off)
- Last frame timestamp and source indicator

**Controls:**
- `⟳ Auto-refresh` - Toggle automatic camera refresh
- `Use EDGE` - Switch to edge detection view
- `Use CAM` - Switch to normal camera view

---

### 2. Manual Movement Controls
**Location:** Below camera

**Controls:**

#### Direction Pad (Grid Layout)
```
        [ ↑ Forward ]
[ ← Left ] [ ■ Stop ] [ Right → ]
        [ ↓ Backward ]
```

#### Speed and Duration Settings
- **Prędkość skrętu** (Turning speed): Slider 0.0 - 1.0 (default: 0.18). Controls yaw (`w`) for left/right spins.
- **Prędkość maksymalna** (Max speed): Slider 0.0 - 1.0 (default: 0.10). Limits the `v` argument for forward/backward moves.
- **Czas impulsu** (Pulse time): Number input in seconds (default: 0.10s)

All commands are validated on the server (`services/api_core/control_proxy.py`), enforcing `v` ∈ `[0,1]` and `t` ≤ safety cap (`SAFE_MAX_T`, default 0.5s).

#### Stop Button
- Dedicated `■ STOP` button for emergency stop

**API Endpoint:** `POST /api/control`

---

### 3. Balance and Height Controls
**Location:** Below movement controls

#### Balance (Stabilization)
- **Checkbox:** Enable/disable robot balance/stabilization
- **API Endpoint:** `POST /api/control/balance`
- **Payload:** `{"enabled": true/false}`

**Use case:** Enable for stable platform, disable for dynamic movement

#### Height (Suspension)
- **Slider:** Adjust robot height (0-255)
- **Default:** 128 (middle position)
- **API Endpoint:** `POST /api/control/height`
- **Payload:** `{"height": 0-255}`

**Use case:** Lower height for stability, higher for obstacle clearance

---

### 4. Vision Tracking (Follow Me)
**Location:** Below balance/height controls

**Modes:**

#### Face Tracking
- **Checkbox:** Enable face tracking mode
- **API Endpoint:** Uses vision tracking system
- **Behavior:** Robot follows detected faces

#### Hand Tracking  
- **Checkbox:** Enable hand tracking mode
- **API Endpoint:** Uses vision tracking system
- **Behavior:** Robot follows detected hand gestures

**Notes:**
- Only one tracking mode can be active at a time
- Disabling checkbox stops all tracking
- Requires vision system to be running

---

### 5. Autonomous Navigation (Rekonesans Mode)
**Location:** Below vision tracking

**Controls:**

#### Enable/Disable Checkbox
- **Label:** "Tryb Rekonesans (Autonomous)"
- **Behavior:** Start/stop autonomous navigation

#### Strategy Selector
Two navigation strategies:
- **STOP** - Stop immediately when obstacle detected (safe mode)
- **AVOID** - Turn right and continue when obstacle detected (exploration mode)

#### Return to Home Button
- **Label:** "🏠 Powrót do Bazy" (Return to Base)
- **Visibility:** Only shown when Rekonesans mode is active
- **API Endpoint:** `POST /api/navigator/return_home`
- **Behavior:** 
  - Stops exploration
  - Calculates path back to start position
  - Navigates autonomously to origin (0, 0)

**API Endpoints:**
- `POST /api/navigator/start` - Start navigation with strategy
- `POST /api/navigator/stop` - Stop navigation
- `POST /api/navigator/config` - Update strategy
- `POST /api/navigator/return_home` - Return to start position

**Status Badge:**
- Shows current navigator state
- States: Idle, Exploring, Avoiding, Stopped, Returning Home, Path Blocked

**Requirements:**
- Vision obstacle detection must be running
- For return-to-home: odometry and mapper services must be active

---

### 6. Provider Control (panel offload)
**Lokalizacja:** pod sekcją Rekonesansu (planowane w kolejnych wydaniach)

**Cel:**
- Prezentacja wybranej ścieżki przetwarzania dla domen (`Vision`, `Voice`, `Text`)
- Status połączenia z Rider-PC (`online`, `degraded`, `offline`)
- Przełączniki `Local (Pi)` / `PC Offload`

**Zachowanie:**
- Odczyt stanu poprzez `GET /api/providers/state`
- Zmiany wysyłane `PATCH /api/providers/{domain}`
- W razie braku Rider-PC panel automatycznie wraca do `Local` i pokazuje ostrzeżenie
- Szerszy opis kontraktu: [OFFLOAD_PROVIDER_PROTOCOL.md](../OFFLOAD_PROVIDER_PROTOCOL.md)

---

### 7. Event Log
**Location:** Bottom of page

**Features:**
- Real-time log of robot actions and events
- Color-coded messages:
  - 🟢 Green (`.ok`) - Successful operations
  - 🟡 Yellow (`.warn`) - Warnings
  - 🔴 Red (`.err`) - Errors
- Auto-scroll to newest entries
- Timestamped events

**Event Types:**
- Movement commands
- Navigator state changes
- Vision tracking events
- API responses
- Error messages

---

## Header Status Indicators

### API Status
- **Location:** Next to page title
- **States:**
  - "(checking…)" - Initial state
  - "✓ API: OK" - API server responsive
  - "✗ API: Error" - API server not responding

### Obstacle Badge
- **Location:** Top right of header
- **States:**
  - Hidden when no obstacle
  - "⚠️ Obstacle: Present" - Obstacle detected
  - Color-coded (yellow/red based on severity)

---

## Keyboard Shortcuts

**Note:** Keyboard control is available when input fields are not focused.

- `W` / `↑` - Forward
- `S` / `↓` - Backward
- `A` / `←` - Turn left
- `D` / `→` - Turn right
- `Space` / `X` - Stop

---

## Browser Compatibility

**Tested browsers:**
- Chrome/Chromium 90+
- Firefox 88+
- Safari 14+
- Edge 90+

**Recommended:** Latest Chrome/Chromium for best performance

---

## Implementation Details

### Auto-refresh Camera
- **Interval:** 1000ms (1 second) when enabled
- **Method:** Appends timestamp to image URL to bypass cache
- **Toggle:** Preserves state across page refreshes

### Event Beacon
On page unload, sends stop command to robot:
```javascript
window.addEventListener('beforeunload', () => {
  navigator.sendBeacon('/api/control', 
    new Blob(['{"cmd":"stop"}'], {type:'application/json'}));
});
```

This ensures robot stops if browser is closed unexpectedly.

### CORS Support
All API calls include proper CORS headers for cross-origin access.

---

## Internationalization

The interface supports Polish (pl) and English (en) languages.

**Automatic detection:** Uses browser language preference  
**Manual override:** Can be set via `?lang=en` or `?lang=pl` query parameter

**Translation keys** (examples):
- `meta.app_title` - Page title
- `motion.title` - Movement section title
- `motion.btn_forward` - Forward button
- `motion.recon_mode` - Rekonesans mode label
- `motion.return_home` - Return to home button

---

## Troubleshooting

### Camera not updating
1. Check if API server is running: `systemctl status rider-api`
2. Verify camera is accessible: visit `http://robot-ip:8080/camera/last`
3. Check auto-refresh is enabled
4. Try switching between CAM and EDGE views

### Navigator not starting
1. Ensure vision system is running: `systemctl status rider-vision`
2. Check obstacle detector: `systemctl status rider-obstacle`
3. Verify API responses in event log
4. Check browser console for JavaScript errors

### Return to Home not working
1. Verify odometry service: `systemctl status rider-odometry`
2. Check mapper service: `systemctl status rider-mapper`
3. Ensure robot has explored area (map exists)
4. Check event log for error messages

### Controls not responding
1. Check API status indicator in header
2. Verify network connectivity to robot
3. Check browser console for errors
4. Try refreshing the page

---

## See Also

- [Navigator API](../api/navigator.md) - Autonomous navigation API
- [Control API](../api/control.md) - Movement control API  
- [Navigator Module](../modules/navigator.md) - Navigation system details
- [Vision Module](../apps/vision.md) - Vision system details
