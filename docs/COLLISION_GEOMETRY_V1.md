# Image collision geometry v1

For the established XGO-Rider CM4 dimensions, camera height and saved image
reference, see [Robot geometry and image reference](ROBOT_GEOMETRY_PL.md).

Automat2 can qualify an observed maneuver envelope instead of requiring an
entire adjacent image sector to be empty. The optional capability is
`collision_geometry_v1: true` on both peers. Existing configurations retain
their legacy sector-and-path checks. There is no automatic migration or motion.

## Configuration and calibration

Pi owns `avoidance.geometry.collision`, only with `mode=image`, enabled
avoidance and protocol 3. All fields below are required.
The optional `guidance` extension is described later.

| Field | Meaning / bounds |
| --- | --- |
| version | Integer 1 |
| far_width_ratio | Far width divided by near corridor width; greater than 0, at most 1 |
| left_shift / right_shift | Endpoint shift in source-image width fractions, 0–1 |
| end_fraction | Terminal-footprint portion of corridor height, 0.05–0.5 |
| reference_corridor | Independent normalized xyxy rectangle for fitting the floor |

The existing `corridor` supplies the near width, center and vertical horizon.
The floor reference must contain that corridor and retain at least the original
0.30 image-width/height support (bounded by the corridor's right/bottom edge).
A narrower collision corridor never automatically narrows the reference.

These are image coordinates, not measured distances or a kinematic model. The
accepted envelope must contain the whole body sweep, its lateral margin and
the footprint at the end of the commanded forward+yaw correction. Calibration
must cover the camera mounting, robot pose and chosen speed/pulse. Saving changed
geometry or motion settings revokes approval and returns to observation; it
does not start a service, ARM or drive. Physical qualification remains separate.

For normalized progress `t=(y1-y)/(y1-y0)`, capped travel is
`s=min(t/(1-end_fraction),1)`. Width is
`(x1-x0)*(1+(far_width_ratio-1)*s)`. Center is the original center plus
`-left_shift*s`, zero, or `right_shift*s`. The final portion keeps the
endpoint center and width: the destination footprint is assessed along with
the sweep. The near guard uses the active temporal profile's near fraction
(or 0.35 for legacy) within the exact forward mask.

A path extending outside the source frame, lacking observed crop/depth pixels,
or lacking reliable floor support is unknown. It is never clipped into a
clear path. Thin intersecting obstacles, signed drop-off evidence and near
STOP precedence remain active. Thresholds and motion limits are unchanged.

## Decision contract

New decisions use `geometry=image_collision_corridor` and
`collision_geometry={version:1,sha256:...}`. SHA-256 covers UTF-8 canonical
JSON with sorted keys and no whitespace:
`{"collision":<normalized configuration>,"corridor":<float xyxy>}`.
All numerical values except integer version are normalized as floats.

The original run/frame/sequence/revision/model/session and capture TTL bind the
proof to the current decision. `paths.center/left/right/guard` contain state,
complete coverage, assessed pixel count and geometry type. Source-image
`sectors` retain their old diagnostic meaning; they are not repurposed.

The new planner counts three qualified current path observations, preserves the
chosen-side and bounded-correction policy, and rejects a mismatched geometry
proof. The Pi permit independently checks the matching proof, forward coverage,
clear near guard and selected path. Legacy permits still require clear sectors.
An unsolicited new proof on a legacy policy is rejected. STOP remains available
without a positive proof. Startup, cold preparation and warm reuse negotiate
the capability before motion authority.

A temporal STOP may permit an existing qualified correction only with three
fresh obstacle observations, valid spatial evidence, a clear near guard and
no hard stop. It cannot override a geometry identity failure. No-progress,
stale decisions, missing post-turn captures and manual/global STOP retain their
existing behavior.

## Operator view and offline analysis

Image settings expose taper, left/right endpoint offsets, terminal footprint
and the separate floor reference. They use the existing stopped, revisioned
configuration transaction. The geometry is opt-in and requires compatible peers.
The overlay and live source-space labels use assessed path masks, not adjacent
sector rectangles. Original sectors remain diagnostic metadata.

The navigation status includes `motion_submission` for the current run: frame,
configuration revision, command sequence, forward speed (`vx`), yaw, duration
and submission outcome (`pending`, `accepted`, `rejected`). The diagnostics show
this separately from observed executor movement. It records the submission
response; a pending response is not a later motor acknowledgement or movement.

The same masks feed spatial/temporal assessment, raster exports, SVG overlays
and saved DA2 analysis. Importing Rider settings into an offline study copies
geometry without approval or actuator authority. Crops must cover the floor
reference; missing maneuver pixels keep the affected side unknown.

## Offline validation

Module: `make check-collision HOST=<venom> RIDER_COLLISION_PI_ROOT=<pi-checkout>
RIDER_COLLISION_PI_PYTHON=<existing-pi-venv>/bin/python`.
The paired test transfers JSON decisions to the companion's real DecisionLease
under its own interpreter, with callbacks that append to a list. It opens no
device connection. Its fixture is `tests/fixtures/replay_collision_lease.py`
in Rider-Pi. Module `make check` also runs the isolated collision-settings
browser fixture.

Pi: `python -m pytest -q tests/test_collision_geometry.py`, plus navigation,
journey, model-input and DecisionLease regression tests. Use the existing venv.

Automated checks establish software behavior only. Physical acceptance must
separately demonstrate left/right avoidance, continuation, repeated obstacles,
and STOP with no available route. Motor acknowledgement alone is insufficient.

## Axis guidance v1: rotation, reobservation and curved steering

An optional `guidance` object inside `avoidance.geometry.collision` selects
the closed-loop behavior. Both peers must additionally advertise
`axis_guidance_v1: true`; the panel exposes the combined availability as
`axis_guidance_supported`. Cold preparation, warm reuse and run startup
negotiate this capability. Older saved policies remain readable and are not
silently converted.

All fields in the nested object are required:

| Field | Meaning / bounds |
| --- | --- |
| version | Integer 1 |
| motion_mode | `rotate_then_drive`, `steer` or `auto` |
| center_deadband | Neutral band around the driving axis, 0–0.25 of corridor half-width |
| rotation_bounds | Calibrated normalized xyxy rectangle covering the body sweep for both rotation directions, or `null` before calibration |

The driving axis is the midpoint of the configured forward corridor. Obstacle
pixels inside that corridor determine the side preference; unrelated objects
at the frame edges do not trigger it. A left obstacle prefers a right correction
and vice versa, with command directions respecting the mirrored-camera setting.
A central or balanced obstacle uses qualified path scores and configured
displacement to break the tie. Preference never overrides a blocked or unknown
maneuver envelope. The selected side stays fixed during one avoidance maneuver
to prevent alternating left/right corrections.

The axis is a reference, not a one-pixel collision test: forward clearance still
requires the full configured body corridor. `axis_evidence` reports the source
axis, normalized obstacle offset, side, pixel counts, intrusion, bounds and the
displacement required to leave either edge of that corridor.

The modes have distinct clearance and motion contracts:

- `rotate_then_drive`: confirm the obstacle, submit STOP, perform one bounded
  in-place rotation (`vx=0`, nonzero yaw), then reassess. Curved paths cannot
  authorize this rotation.
- `steer`: qualify the selected full forward+yaw sweep, execute a bounded
  curved correction and reassess. Rotation is not permitted.
- `auto`: on the selected/preferred side, use a qualified curved path first;
  otherwise use a separately qualified rotation. It does not fabricate either
  type of clearance.

Rotation uses its own `paths.rotation` mask, not the left/right curved masks.
The common envelope must span the near body corridor and its bottom edge, fit
inside the source frame and contain at least 64 observed depth pixels.
Missing depth, incomplete input crop, poor plane support or an obstacle makes
it ineligible. A new guided draft defaults to `rotate_then_drive` with
`rotation_bounds: null`: observation and saving remain available, but drive
requires calibration and a model input covering the whole rectangle. In
`auto`, missing rotation calibration leaves only qualified curves available.

The rectangle is a conservative image envelope, not an inferred measurement
of the robot. Calibration must cover the actual body sweep, camera pose,
rotation speed and pulse duration in both directions. An image that cannot
observe that sweep cannot authorize a rotation through this contract.

Three consecutive qualified obstacle/path observations are required. Before
each in-place rotation the planner emits STOP; Pi independently requires the
prior zero submission. After every correction, captures from before the
Pi-local permit end plus 100 ms settling cannot authorize further nonzero
motion. Three fresh clear full-corridor observations release forward travel.
A continuous journey resets the avoidance budget only through its existing
maneuver-epoch transition and can then handle the next obstacle.

Progress is the relative reduction in the remaining image displacement toward
the selected exit, measured after a correction. It can improve while the
obstacle is still inside the corridor. Existing minimum-progress,
stalled-correction and maximum-pulse bounds apply. Missing observations,
blocked selected direction, near guard, recess evidence, manual STOP and TTL
expiry cannot be bypassed. A temporal policy veto does not consume a correction
attempt or create motion progress.

The canonical collision SHA-256 includes the entire normalized guidance
object (both version fields stay integers). Decisions also carry
`guidance={version:1,motion_mode:...}`. Pi independently verifies configuration
identity, selected mode, appropriate path proof, fresh capture and motion
limits before choosing its rotation or steering callback.

## Existing panel and phase-two regression checks

The existing image-geometry settings contain the correction mode, axis neutral
band and rotation calibration fields. The decision view identifies obstacle
side and rotation clearance; source overlays draw the driving axis and the
independent rotation envelope. Saving a changed configuration retains the
existing approval revocation and observe-only behavior. No extra tab or
automatic live trial is introduced.

`make check-collision` includes `tests/test_axis_guidance.py`. Its paired
offline journey sends real module decisions to the Pi DecisionLease under the
Pi interpreter: two obstacles on opposite sides, STOP, rotation, post-correction
capture, resumed forward movement, and the next maneuver. It runs both camera
orientations with list-only motion callbacks. Pi tests also check the actual
runner's separate zero-forward rotation and nonzero-forward steering payloads
using a mocked submitter.

Pi targeted checks include both `tests/test_collision_geometry.py` and
`tests/test_axis_guidance.py`, followed by navigation and journey regressions.
The isolated browser fixture verifies rotation calibration, mode selection
and the blocked-start state. These checks do not connect to or drive the robot.
