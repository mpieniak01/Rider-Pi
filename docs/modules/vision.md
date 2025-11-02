# Vision Module — Object Detection and Depth Estimation

## Overview

The **Vision** module provides computer vision capabilities for the Rider-Pi robot, including:
- Object detection (faces, persons, obstacles)
- Event normalization and debouncing (dispatcher)
- Depth estimation for SLAM mapping (Stage 3 addition)

## Components

### 1. Dispatcher (`apps/vision/dispatcher.py`)

Central hub for vision events that:
- Subscribes to detector outputs (`vision.face`, `vision.person`, `vision.detections`)
- Normalizes different detector formats
- Applies debouncing/hysteresis to reduce noise
- Publishes unified state (`vision.state`)

**Topics:**
- IN: `vision.face`, `vision.person`, `vision.detections`
- OUT: `vision.state`, `vision.dispatcher.heartbeat`

### 2. Obstacle Detector (`apps/vision/obstacle_roi.py`)

Edge-based obstacle detection:
- Analyzes bottom ROI (Region of Interest) of camera image
- Detects obstacles based on edge scarcity (wall/obstacle blocks view)
- Safety checks for darkness and blur
- Publishes obstacle presence and confidence

**Topics:**
- OUT: `vision.obstacle`

### 3. Depth Estimation Bridge (`apps/vision/depth_bridge.py`) — **NEW (Stage 3)**

Integrates depth estimation for SLAM mapping:
- Monitors navigator state
- When reconnaissance mode is active, estimates obstacle distances
- Converts obstacle detections to (angle, distance) pairs
- Publishes data for mapper consumption

**Topics:**
- IN: `navigator.state`, `vision.obstacle`
- OUT: `vision.obstacle.data`

## Depth Estimation (Rekonesans Stage 3)

### Purpose

Provides distance information for obstacles detected by the vision system, enabling the mapper to build an accurate occupancy grid.

### Current Implementation

**Simplified Distance Estimation:**
The current implementation uses a simplified model based on obstacle detection confidence:
- High confidence (≥0.9) → closer obstacle (~0.3-1.0m)
- Medium confidence (~0.7) → medium distance (~1.5m)
- Low confidence (~0.5) → farther obstacle (~2.5-3.0m)

**Data Format:**
```json
{
  "obstacles": [
    {"angle": 0.0, "distance": 1.5},
    {"angle": 0.2, "distance": 1.8},
    ...
  ],
  "ts": 1234567890.123,
  "source": "simplified_depth"
}
```

- `angle`: Horizontal angle in radians (0 = straight ahead, + = left, - = right)
- `distance`: Distance in meters
- `source`: Indicates depth estimation method

### Future Enhancement: Mono-Depth Estimation

**Planned Implementation:**
The simplified model is a placeholder for full mono-depth estimation using deep learning:

1. **Model**: TFLite-optimized mono-depth estimation model
   - Example: MobileNetV2-based depth estimator
   - Input: Single RGB camera image
   - Output: Per-pixel depth map

2. **Integration Points**:
   - Add model file to `data/models/depth_estimation.tflite`
   - Modify `depth_bridge.py` to load and run TFLite inference
   - Process depth map to extract obstacle points

3. **Camera Calibration**:
   - Calibrate camera intrinsics (focal length, optical center)
   - Use calibration to convert pixel coordinates + depth to 3D points
   - Project 3D points to (angle, distance) in robot frame

4. **Multi-Point Detection**:
   - Instead of single center point, extract multiple points across obstacle surface
   - Provides richer map representation
   - Enables detection of obstacle shape and extent

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `VISION_DEFAULT_OBSTACLE_DISTANCE` | `1.5` | Default obstacle distance (m) |
| `VISION_MIN_OBSTACLE_DISTANCE` | `0.3` | Minimum distance (m) |
| `VISION_MAX_OBSTACLE_DISTANCE` | `3.0` | Maximum distance (m) |
| `VISION_CAMERA_FOV_H` | `60.0` | Camera horizontal FOV (degrees) |

## Running Vision Components

### Obstacle Detector
```bash
python3 apps/vision/obstacle_roi.py
```

### Depth Bridge (Stage 3)
```bash
python3 apps/vision/depth_bridge.py
```

### Dispatcher
```bash
python3 apps/vision/dispatcher.py
```

## Integration with Rekonesans Epic

### Stage 1: Navigator
- Vision provides obstacle detection (`vision.obstacle`)
- Navigator uses it for reactive avoidance

### Stage 2: Odometry
- No direct vision integration
- Provides pose for Stage 3 mapping

### Stage 3: Mapper (with Depth)
- Vision depth bridge provides obstacle distances
- Mapper fuses pose + obstacle data to build occupancy grid

## Data Flow (Stage 3)

```
[Camera] → [Obstacle Detector] → vision.obstacle
                                        ↓
                                  [Depth Bridge] ← navigator.state
                                        ↓
                                vision.obstacle.data
                                        ↓
                                    [Mapper]
```

## Testing

Currently no automated tests for vision components (integration testing only).

**Manual Testing:**
1. Start obstacle detector and depth bridge
2. Start navigator in reconnaissance mode
3. Monitor `vision.obstacle.data` topic for depth estimates
4. Verify mapper receives and processes obstacle data

## Future Work

### Short-term (Stage 3 Enhancement)
- [ ] Integrate actual mono-depth TFLite model
- [ ] Camera intrinsic calibration
- [ ] Multi-point obstacle extraction from depth map
- [ ] Angle estimation from bbox horizontal position

### Long-term
- [ ] Stereo depth estimation (if dual cameras available)
- [ ] Visual odometry integration with IMU
- [ ] Object recognition for semantic mapping
- [ ] Visual SLAM (feature tracking + mapping)

## Known Limitations

1. **Simplified Depth**: Current distance estimation is heuristic-based, not measurement-based
2. **Single Point**: Only one obstacle point per detection (center)
3. **Fixed Angle**: Assumes obstacle is straight ahead (0° angle)
4. **Camera-Dependent**: FOV and accuracy depend on camera model
5. **No Calibration**: Assumes default camera parameters

## See Also

- `docs/modules/navigator.md` - Obstacle avoidance (Stage 1)
- `docs/modules/odometry.md` - Position tracking (Stage 2)
- `docs/modules/mapper.md` - Occupancy grid mapping (Stage 3)
- `apps/vision/obstacle_roi.py` - Obstacle detection implementation
- `apps/vision/depth_bridge.py` - Depth estimation bridge
