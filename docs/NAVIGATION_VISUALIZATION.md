# Navigation Visualization System

## Overview

The navigation visualization system provides real-time monitoring and debugging capabilities for the robot's navigation stack. It displays the robot's position, map data, and planned paths in a web-based interface accessible at `/navigation`.

## Architecture

### Components

1. **Frontend** (`web/navigation.html`)
   - HTML5 Canvas-based visualization
   - WebSocket client for real-time data streaming
   - Auto-reconnection on connection loss
   - Responsive layout

2. **Backend Bridge** (`services/navigation_websocket_bridge.py`)
   - Subscribes to navigation-related bus topics
   - Transforms data for frontend consumption
   - Broadcasts to multiple WebSocket clients
   - Caches last known data for new clients

3. **Data Sources**
   - **Odometry** (`apps/odometry/main.py`): Robot position tracking
   - **Mapper** (`apps/mapper/main.py`): Occupancy grid mapping
   - **Navigator** (`apps/navigator/main.py`): Path planning

### Data Flow

```
┌──────────────┐
│   Odometry   │──► TOPIC_ROBOT_POSE
└──────────────┘        │
                        │
┌──────────────┐        │     ┌─────────────────────┐
│    Mapper    │──► TOPIC_MAPPER_MAP_DATA ──► │ WebSocket Bridge │
└──────────────┘        │     └─────────────────────┘
                        │              │
┌──────────────┐        │              │
│  Navigator   │────────┘              │
└──────────────┘                       │
                                       ▼
                              ┌─────────────────┐
                              │  /ws/navigation │
                              └─────────────────┘
                                       │
                                       ▼
                              ┌─────────────────┐
                              │  Web Browser    │
                              │  /navigation    │
                              └─────────────────┘
```

## Usage

### Starting the System

1. **Start the message broker:**
   ```bash
   make broker
   ```

2. **Start the API server** (includes WebSocket endpoint):
   ```bash
   make api
   ```

3. **Access the visualization:**
   Open your browser to `http://localhost:8080/navigation`

### Running a Demo

To test the system with simulated data:

```bash
# Terminal 1: Start broker
make broker

# Terminal 2: Start API server
make api

# Terminal 3: Run demo publisher
python3 scripts/demo_navigation_websocket.py
```

The demo will publish simulated robot movement in a circular path.

## WebSocket Protocol

### Endpoint
- **URL**: `ws://localhost:8080/ws/navigation` (or `wss://` for HTTPS)

### Message Types

#### 1. Odometry Update
```json
{
  "type": "odometry",
  "data": {
    "x": 1.5,      // meters
    "y": 2.3,      // meters
    "angle": 0.785 // radians
  }
}
```

#### 2. Map Update
```json
{
  "type": "map",
  "data": {
    "width": 50,
    "height": 50,
    "data": [0, 1, 2, ...], // Flattened grid
    "origin": {
      "x": 25.0,
      "y": 25.0
    }
  }
}
```

Grid values:
- `-1`: Unknown/unexplored
- `0`: Free space
- `1`: Obstacle
- `2`: Visited/explored

#### 3. Path Update (Future)
```json
{
  "type": "path",
  "data": {
    "path": [
      {"x": 0, "y": 0},
      {"x": 1, "y": 1},
      ...
    ],
    "target": {"x": 10, "y": 10}
  }
}
```

## Visualization Elements

The frontend renders the following:

1. **Occupancy Grid**: Shows known obstacles, free space, and unexplored areas
2. **Robot Position**: Cyan circle with direction indicator
3. **Start Position**: Green circle marking the origin
4. **Target**: Yellow star (when path planning is active)
5. **Planned Path**: Blue line showing the navigator's planned route
6. **Traveled Path**: Gray line showing actual path taken
7. **Legend**: Color-coded key for all elements

## Configuration

### Environment Variables

#### WebSocket Bridge
- `NAV_WS_LOG_LEVEL`: Log level (DEBUG, INFO, WARNING, ERROR) [default: INFO]

#### Odometry
- `ODOMETRY_UPDATE_RATE_HZ`: How often to update position [default: 10.0]
- `ODOMETRY_PUBLISH_RATE_HZ`: How often to publish to bus [default: 5.0]

#### Mapper
- `MAPPER_MAP_WIDTH_M`: Map width in meters [default: 10.0]
- `MAPPER_MAP_HEIGHT_M`: Map height in meters [default: 10.0]
- `MAPPER_MAP_RESOLUTION_M`: Cell size in meters [default: 0.05]

## Development

### Running Tests

```bash
# Test the WebSocket bridge
python3 -m pytest tests/test_navigation_websocket.py -v

# Test the web route
python3 -m pytest tests/test_web_routes.py::test_navigation_page_no_redirect -v
```

### Code Style

The project uses `ruff` for linting and formatting:

```bash
# Check code
python3 -m ruff check services/navigation_websocket_bridge.py

# Format code
python3 -m ruff format services/navigation_websocket_bridge.py
```

## Troubleshooting

### WebSocket Not Connecting

1. **Check broker is running**: The ZMQ broker must be active
   ```bash
   make broker
   ```

2. **Check API server**: Verify the server started without errors
   ```bash
   make api
   ```

3. **Check browser console**: Look for WebSocket connection errors
   - Open browser DevTools (F12)
   - Check the Console tab for errors

### No Data Displayed

1. **Verify data sources are publishing**:
   ```bash
   # Monitor bus traffic
   python3 scripts/diag_bus-spy.py
   ```

2. **Check topics**:
   - `robot.pose` should show odometry data
   - `mapper.map.data` should show map updates

3. **Check WebSocket bridge logs**: Look for data processing messages

### Performance Issues

- **Reduce map size**: Lower `MAPPER_MAP_WIDTH_M` and `MAPPER_MAP_HEIGHT_M`
- **Increase cell size**: Raise `MAPPER_MAP_RESOLUTION_M`
- **Lower update rates**: Reduce `ODOMETRY_PUBLISH_RATE_HZ`

## Future Enhancements

- [ ] Path planning visualization (Navigator integration)
- [ ] Obstacle detection overlay (Vision integration)
- [ ] Historical path replay
- [ ] Map export/import functionality
- [ ] Multi-robot support
- [ ] Performance metrics display
- [ ] Touch controls for mobile devices

## Dependencies

- **flask-sock** (≥0.7.0): WebSocket support for Flask
- **pyzmq**: ZeroMQ Python bindings for message bus
- **flask**: Web framework

See `requirements-dev.txt` for complete dependency list.
