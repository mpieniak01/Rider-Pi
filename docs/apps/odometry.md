# Odometry and navigation data quality

Odometry is a model estimate from accepted SDK output and IMU observations. It is
not a localization sensor. There is no measured accuracy, speed or stopping
distance in this release. Hardware characterization is local operator work.
#256 provides [configuration and calibration tools](calibration.md), which
can be reviewed and released independently of entering physical measurements.

## Sources and validity

- `motion.output`: actual accepted signed `linear_step` / `turn_step`, source
  `motion-executor`, instance_id, generation, original `observed_at`, stopped and accepted.
  Requested `motion.command` or legacy `motion` cannot update the position model.
- `imu.data`: finite yaw and original observation time. IMU is required; missing
  IMU never switches automatically to a guessed angular velocity.
- `robot.pose`: x/y/theta, original oldest source `observed_at`, publication `ts`,
  calibration_id, reference_id, data_ready, navigation_ready and error.
  `home` is an explicit operator report in that same reference/calibration.
  Pose-model validity alone never enables autonomous navigation.
  Confidence is `null` with `confidence_kind=unquantified_model`; it is not a
  probability or an accuracy guarantee. `physical_completion=unverified`.

Elapsed integration uses monotonic time. Output freshness is 0.25 s, IMU freshness
2.5 s and maximum integration dt 0.2 s. These are software input budgets, not
physical limits. Stale, future, missing or out-of-order inputs cannot refresh a
pose. Accepted nonzero output already counts as potential movement, even before
the first integration step. A gap or unobserved generation transition makes
continuity unknown until a new manual reference. A new executor instance also
invalidates the reference. Publication `ts` never replaces absent `observed_at`.

During idle, an independently received fresh accepted SDK zero can remain the
model's last command while matching `motion.state` heartbeats confirm the same
executor instance/generation, zero output/target and healthy stationary state.
The heartbeat has a 3 s source and monotonic arrival budget; IMU must remain fresh.
It cannot supply a missing SDK write or repair a history gap. The original write
time stays in `last_sdk_output_observed_at`; idle pose `observed_at` is the oldest
heartbeat/IMU observation supporting the current estimate. A stale STOP without
this continuity cannot confirm a new manual reference. These are model inputs,
not evidence of mechanical stopping; `physical_completion` remains `unverified`.
MOVE admission can arrive before its independent SDK output. A healthy matching
executor transition may defer the model for up to 0.25 s with `sdk_output_pending`;
it cannot integrate movement, refresh the STOP or extend that wait with heartbeats.
Missing output, a liveness gap, invalid integration dt or stale IMU still breaks
continuity. Only the independently received accepted SDK write ends the wait.

## Recorded model

The Calibration panel manages local revisions of the motion and odometry profile.
After explicit application, `calibration_id` is the exact revision digest, while
`measurement_id` remains a measurement label. A revision change invalidates
reference/HOME and previous map cells, including before a new reference is set.
Saving a draft and accepting configuration do not verify the physical model.

When no panel profile exists, the legacy interface remains available:
`ODOMETRY_CALIBRATION_PATH` optionally points to a bounded JSON record. Start with
[`config/odometry-calibration.example.json`](../../config/odometry-calibration.example.json).
The example is intentionally unverified and contains no physical numbers.

Only a manually verified record with a measurement ID, firmware/surface/load/
battery conditions, checked IMU sign, and exact signed SDK step tables is usable.
`linear_m_s` maps signed SDK integer steps to measured m/s. `turn_rad_s` maps
signed SDK steps to measured CCW rad/s. Zero is always the zero command. Missing
steps are rejected; the model does not interpolate. Legacy normalized-speed
scales are not physical calibration and are no longer used.

Measurements apply only to their recorded conditions. Ramp settings remain in
normalized command units; the adapter's minimum nonzero SDK step prevents any
claim that small UI values produce arbitrarily slow physical motion.

## Current reference

A stored calibration never restores the robot's current location. Each odometry
process starts with an unknown reference. While the executor is confirmed fresh,
stationary and DISARMED, an operator may verify position/heading and submit one
explicit reference:

```text
GET  /api/odometry/state
POST /api/odometry/reference
```

POST requires generation, source=`manual`, monotonic per-generation seq,
request_id, original ts, ttl_ms<=500, operator_consent=true, a concrete
operator_plan and finite x/y/theta (meters/radians, CCW positive). The API returns
202 pending. Only a matching process ACK confirms the origin update; this ACK
does not prove movement or calibration. GET never starts a process or actuator.
BUS topics are `odometry.reference` and `odometry.reference.ack`.

Current position is not automatically HOME. To record an independently checked
HOME, the same request includes `home_operator_confirmed=true` and finite
`home_x`/`home_y` in the same frame. Otherwise HOME remains unknown, with no
default `(0,0)`. A replacement reference without HOME clears previous HOME;
restart/executor replacement never restores it. GET/ACK project the reported
HOME with its exact reference_id/calibration_id. The CLI offers explicit
`--home-x` and `--home-y`; both are supplied together or neither.

The interactive, non-actuating helper is `scripts/manual_odometry-reference.py`.
The operator supplies measured coordinates and a plan, then confirms REFERENCE.
CI/non-TTY/test isolation is refused. A command from before process start and a
persistently consumed generation/seq are rejected. Reference is not restored
after restart. State and sequence consumption live in `/run/rider-motion`;
`ODOMETRY_STATE_DIR` is an isolated fixture override.

## Mapper and return home

Mapper accepts only fresh calibrated poses and verified range geometry, footprint
and traversal/stopping-horizon records. It bounds allocations to 65,536 cells, preserves each
cell's original observation time and ages old cells to UNKNOWN. Map requests echo
request_id and never make data newer. Unknown cells and diagonal corner cutting
are not traversable in a point plan. Map and pose must have exactly matching
reference_id/calibration_id and HOME; a changed frame clears previous cells/range.
Missing range/pose/HOME prevents a plan. `planning_ready` describes usable inputs;
mapper `navigation_ready` remains false.

**Exploration and ReturnHome are passive in this release.** They cannot publish
MOVE, including a zero MOVE. ReturnHome releases the motion lease with canonical
STOP and may present a matching bounded point A* plan (`planning_only`,
`planned_path`, maximum 128 displayed points). FREE cells or positive
`stopping_horizon_m` with verification flags do not prove swept-body clearance or
braking. The controller reports `navigation_traversal_unverified`, never physical
arrival or motion readiness. No metadata boolean enables an autonomous actuator.
Physical corridor/braking characterization and an independently reviewed
planner/guard are pending. Manual drive retains its separate operator lease.

The front camera ROI detector indicates a heuristic obstacle; it is **not a
calibrated distance or proof that the robot's footprint can traverse a corridor**.
Do not derive a free occupancy map from a missing frame, empty obstacle list or
confidence zero. SDK output confirmation also does not prove physical arrival.

See [manual characterization and open acceptance checklist](physical-motion.md).
