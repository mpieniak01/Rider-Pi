# Follow Me Tracking Feature

This feature enables the robot to track and follow faces or hands using MediaPipe detection, rotating to keep the tracked object centered in the camera's field of view.

## Architecture

The tracking system consists of two main components:

1. **Vision Tracker** (`apps/vision/tracker_mediapipe.py`)
   - Subscribes to unified control topic: `tracking.mode:set`
   - Performs MediaPipe-based face/hand detection
   - Publishes horizontal offset to `vision.tracking.offset`

2. **Motion Controller** (`apps/motion/tracking_controller.py`)
   - Subscribes to `vision.tracking.offset`
   - Uses proportional controller to convert offset to rotation commands
   - Includes dead zone and timeout for stability

## Installation

### Option 1: Systemd Services (Recommended for Production)

The tracking modules are integrated as systemd services:

```bash
# Enable and start the vision tracker
sudo systemctl enable rider-tracker.service
sudo systemctl start rider-tracker.service

# Enable and start the motion controller
sudo systemctl enable rider-tracking-controller.service
sudo systemctl start rider-tracking-controller.service

# Check status
sudo systemctl status rider-tracker.service
sudo systemctl status rider-tracking-controller.service

# View logs
sudo journalctl -u rider-tracker.service -f
sudo journalctl -u rider-tracking-controller.service -f
```

### Option 2: Manual Execution (Development/Testing)

For testing or development, you can run the modules manually:

```bash
# Terminal 1: Vision tracker
python3 -m apps.vision.tracker_mediapipe

# Terminal 2: Motion controller
python3 -m apps.motion.tracking_controller
```

## Configuration

Both services can be configured via environment variables. You can create override files:

### Vision Tracker Configuration

Create `/etc/default/rider-tracker`:
```bash
# Camera FPS limit
TRACKING_MAX_FPS=10.0

# Dead zone threshold
TRACKING_DEAD_ZONE=0.1

# Snapshot directory
SNAP_BASE=/home/pi/robot/snapshots
```

### Motion Controller Configuration

Create `/etc/default/rider-tracking-controller`:
```bash
# Proportional gain (higher = more responsive)
TRACKING_KP=0.15

# Dead zone threshold (no action if |offset| < this)
TRACKING_DEAD_ZONE=0.1

# Timeout in seconds (stop if no updates)
TRACKING_TIMEOUT=1.0

# Maximum rotation speed (0..1)
TRACKING_MAX_SPEED=0.20

# Enable motion
MOTION_ENABLE=1
```

Then reload and restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart rider-tracker.service
sudo systemctl restart rider-tracking-controller.service
```

## Usage

Once the services are running, use the web panel at `http://<robot-ip>:8080/control`:

1. **Follow Face**: Toggle "Śledź Twarz" to track faces
2. **Follow Hand**: Toggle "Śledź Dłoń" to track hands
3. **Stop Tracking**: Disable both toggles

The toggles are mutually exclusive - enabling one automatically disables the other.

## Tuning

### Responsiveness

- Increase `TRACKING_KP` for faster response (but may cause oscillation)
- Decrease `TRACKING_KP` for smoother, slower tracking

### Stability

- Increase `TRACKING_DEAD_ZONE` to reduce jitter in the center
- Decrease `TRACKING_DEAD_ZONE` for tighter centering
- Adjust `TRACKING_TIMEOUT` to control how long to wait before stopping

### Performance

- Lower `TRACKING_MAX_FPS` to reduce CPU usage
- Increase `TRACKING_MAX_SPEED` for faster rotation (but less smooth)

## Troubleshooting

### Services not starting

Check logs:
```bash
sudo journalctl -u rider-tracker.service -n 50
sudo journalctl -u rider-tracking-controller.service -n 50
```

Common issues:
- MediaPipe not installed: `pip3 install mediapipe`
- Camera not accessible: Check camera permissions
- Serial port conflict: Ensure XGO_PORT is correct

### Robot not rotating

1. Check motion controller is running: `systemctl status rider-tracking-controller.service`
2. Verify MOTION_ENABLE=1 in configuration
3. Check XGO serial port: `ls -l /dev/ttyAMA0`
4. Review logs for errors

### Tracking not responding

1. Verify tracker service is running: `systemctl status rider-tracker.service`
2. Check broker is running: `systemctl status rider-broker.service`
3. Test API endpoint manually:
   ```bash
   # Enable face tracking
   curl -X POST http://localhost:8080/api/vision/tracking/mode -H "Content-Type: application/json" -d '{"mode": "face", "enabled": true}'
   
   # Enable hand tracking
   curl -X POST http://localhost:8080/api/vision/tracking/mode -H "Content-Type: application/json" -d '{"mode": "hand", "enabled": true}'
   
   # Disable tracking
   curl -X POST http://localhost:8080/api/vision/tracking/mode -H "Content-Type: application/json" -d '{"mode": "none", "enabled": false}'
   ```

## Dependencies

- Python 3.9+
- mediapipe
- opencv-python (cv2)
- pyzmq
- flask (for API)

Install with:
```bash
pip3 install mediapipe opencv-python pyzmq flask
```
