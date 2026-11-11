# Image collision geometry v1

Automat2 can qualify an observed maneuver envelope instead of requiring an
entire adjacent image sector to be empty. The optional capability is
`collision_geometry_v1: true` on both peers. Existing configurations retain
their legacy sector-and-path checks. There is no automatic migration or motion.

## Configuration and calibration

Pi owns `avoidance.geometry.collision`, only with `mode=image`, enabled
avoidance and protocol 3. All fields are required:

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
