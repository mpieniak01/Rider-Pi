# Rider-Pi Web UI Documentation

This directory contains documentation for the Rider-Pi web user interfaces.

## Available Interfaces

### [control.html](control.md)
Main control interface for robot movement, camera, and autonomous navigation.

**URL:** `http://robot-ip:8080/control.html`

**Features:**
- Camera live preview
- Manual movement controls
- Balance and height adjustment
- Vision tracking (Follow Me)
- Autonomous navigation (Rekonesans mode)
- Event log

---

### home.html
Landing page with system overview and navigation.

**URL:** `http://robot-ip:8080/home.html` or `http://robot-ip:8080/`

---

### chat.html
Voice and text chat interface.

**URL:** `http://robot-ip:8080/chat.html`

**Features:**
- Text chat with AI assistant
- Voice input/output
- Conversation history

---

### view.html
Vision system viewer and camera controls.

**URL:** `http://robot-ip:8080/view.html`

**Features:**
- Camera stream with detection overlays
- Face/person/object detection visualization
- Vision system status

---

### system.html
System dashboard with live systemd service overview.

**URL:** `http://robot-ip:8080/web/system.html`

**Features:**
- Status kart services (`active`, `inactive`, `failed`, `unknown`)
- Wizualizacja zależności logicznych (graf powiązań)
- Tabela z opisami i czasem aktywacji jednostek
- Automatyczne odświeżanie co 5 s

---

### google_home.html
Google Home integration and device management.

**URL:** `http://robot-ip:8080/google_home.html`

**Features:**
- Google Home device pairing
- Smart home control
- Voice command testing

---

## Common Features

### Internationalization (i18n)
All interfaces support Polish (pl) and English (en) languages.

**Implementation:** `web/i18n.js`

Language is automatically detected from browser settings or can be manually selected.

### API Integration
All UIs communicate with the robot via REST API on port 8080.

**Base URL:** `http://robot-ip:8080/api`

### Real-time Updates
Some interfaces use polling or WebSocket connections for real-time data updates.

---

## Development

### Testing Locally
The web interfaces can be tested locally by running the API server:

```bash
python3 -m services.api_server
```

Then open `http://localhost:8080/control.html` in your browser.

### File Structure
```
web/
├── control.html      # Main control interface
├── home.html         # Landing page
├── chat.html         # Chat interface
├── view.html         # Vision viewer
├── system.html       # System dashboard (status + graph)
├── google_home.html  # Google Home integration
└── i18n.js          # Internationalization support
```

---

## See Also

- [API Documentation](../api/README.md) - REST API endpoints
- [ARCHITECTURE.md](../../ARCHITECTURE.md) - System architecture
- [Vision Module](../apps/vision.md) - Vision system
- [Navigator Module](../modules/navigator.md) - Autonomous navigation
