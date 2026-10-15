# Vision Module — Object Detection and Depth Estimation

## Overview

The **Vision** module provides computer vision capabilities for the Rider-Pi robot, including:
- Object detection (faces, persons, obstacles)
- Event normalization and debouncing (dispatcher)
- Depth estimation for SLAM mapping (Stage 3 addition).

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

### 4. Tracker MediaPipe (`apps/vision/tracker_mediapipe.py`) — **Follow Me Visual Stream**

MediaPipe-based face and hand tracking with visual feedback:
- Real-time face and hand detection using MediaPipe
- Publishes tracking offset data for motion controller
- Generates annotated video stream with:
  - **FPS overlay** — processing frames per second (minimum acceptable: 10 FPS)
  - **Detection circle** — visual marker around tracked object (face/hand)
- Saves frames to `snapshots/tracker.jpg` for web UI consumption

**Modes:**
- `FACE` — track face for Follow Me
- `HAND` — track hand for Follow Me
- `NONE` — idle mode (no processing)

**Topics:**
- IN: `tracking.mode:set` (unified mode control)
- OUT: `vision.tracking.offset`

**API Endpoints:**
- `/vision/tracker` — GET — retrieve latest annotated tracker frame (JPEG)
- `/vision/snap-info` — includes tracker frame age and metadata
- `/vision/tracking/mode` — POST — unified tracking mode control
  - Payload: `{"mode": "face"|"hand"|"none", "enabled": true|false}`
  - Example: `{"mode": "hand", "enabled": true}` enables hand tracking
  - Example: `{"mode": "face", "enabled": false}` disables tracking (sets mode to "none")

**Configuration:**
```bash
TRACKING_DEAD_ZONE=0.1      # Center dead zone (±10%)
TRACKING_MAX_FPS=10.0       # FPS limit for CPU efficiency
SNAP_BASE=/path/to/snapshots # Frame output directory
```

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


## Supervised GO/STOP loop

POST /api/navigation/trial admits one explicit operator request: request_id, generation, Pi-clock ts/ttl_ms (up to 500 ms), config_revision, settings_revision, operator_consent=true, operator_plan, source=manual and execution_context=panel. Pi serializes preparation through FeatureManager (up to 5 s), retains its existing configuration, grants one navigation ARM for at most 10 s and confirms the new run. A replayed request_id cannot ARM again.

Fresh obstacle or image uncertainty sends an immediate zero goal within that original trial. Three new CLEAR observations may resume small forward pulses without rearming or extending 10 s. Expired decisions, communication loss, contract/executor failure, operator STOP, manual takeover and ARM expiry are terminal. Existing thresholds and motion limits are unchanged.

The live executor must advertise scoped_stop_generation_supported=true and remote_decision_deadline_supported=true. Optional expected_generation in STOP/disarm is checked atomically before revocation; old cleanup cannot stop a new owner. Global STOP without this field remains unconditional. Updating code requires the current executor process, not only a panel restart.


### Close STOP band for slow starts

New configurations default to `corridor=[0.35,0.80,0.65,0.95]`: the closest 15% of image height with the previous path width. Saved configurations are not automatically migrated. Venom offers Near / Farther (15% / 30%), writing only the existing Pi-owned `corridor` field.

Selecting Near never increases speed or pulse duration and caps the selection at 0.1 SDK and 150 ms. Ramps, deadlines, the 10-second trial limit and STOP remain unchanged. Changing the corridor invalidates the old acceptance and leaves observe mode; saving alone never arms or starts driving. Inspect fresh analysis and use the existing acceptance button for the current zone.

The white frame is the STOP zone. Venom geometry retains broader ground-fitting support (at least 30% of image height), shown with a dashed blue outline. Do not fit the plane exclusively to the smaller zone: a broad flat obstacle could become the fitted ground. These are image coordinates, not calibrated centimetres or stopping-distance measurements.


### Warm observation-to-trial handoff

The trial first reserves the existing passive camera consumer, then releases the
previous observation/drive producer. Shared camera capture and frame distribution
are not restarted in a warm handoff. A failed preparation keeps the passive
reservation; it never restores driving or ARM. Other operator STOP/takeover remains
authoritative.

The navigation status includes preparation request_id, phase, state, elapsed_ms
and freshness, even when no producer file exists. Timeout errors include the
failed phase. Unit observations are reused only inside the preparation transaction
and invalidated after unit actions; motion authority is always read fresh.
Service preparation is bounded by 15 s, with at most 5 s for final startup after ARM within that budget. Motion and decision limits are unchanged.


### Production timing: a motor permit is not a trial lifetime

A recorded Pi trial reached two GO decisions but expired the previous short motor
permit while the next fresh reply was in flight. The runner now distinguishes the
executor-enforced pulse/decision deadline from feedback liveness. At permit expiry
the motor output is already zero under the executor's bounded command; the old GO
cannot be reused. The active trial may wait at zero until the last valid reply plus
the existing decision_budget_ms. Only a new valid frame/revision/sequence can
issue another bounded pulse. No ARM renewal or higher motion/deadline limit is
introduced. Missing feedback at that limit, stale/invalid replies, explicit STOP,
transport errors and authority changes terminate the trial.

Status exposes separate permit_remaining_ms and feedback_remaining_ms. The API
reports waiting_feedback and a STOP reply when the motor permit has expired.
Internal process-start monotonic timestamps are checked on Pi, not compared with
browser clocks. A matching run that started/stopped during HTTP bookkeeping is
reported as that actual run outcome, not as never started. Idempotent task stop
returns observed task evidence so the negotiated HTTP contract does not create a
spurious 502 for a completed cancellation.

Tests include the numerical sequence recorded on Pi on 2026-10-15 at12:45,
independent executor pulse expiry, network failure, late HTTP acknowledgement and
foreign run rejection. Physical acceptance remains separate.


### Accepted operating scene

On 2026-10-15 the operator confirmed a stable forward GO/STOP process in the
currently calibrated physical floor scene. This is acceptance of that scene and
the saved low-speed setup, not a metric distance or general scene guarantee.

A valid decision with less than 50 ms remaining for a pulse submits only ZERO
and waits within the existing feedback budget. A new fresh GO may resume the
same original ARM, without renewing its deadline or increasing speed/duration.
Missing feedback, expired images, invalid identities and executor errors still
terminate the trial. Venom reports image verdict and actual execution separately.
