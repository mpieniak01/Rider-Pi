# Optional turns in the Venom vision loop

Pi remains authoritative for policy and actuation. Avoidance is disabled by
default. Existing saved navigation policies migrate to disabled avoidance;
forward-only protocol v1 remains available and cannot execute turn actions.

The existing navigation_config.json adds avoidance: enabled, sweep_verified,
mirrored (booleans), turn_speed (0.01–0.1 SDK, default 0.05), turn_ms (50–150,
default 100), max_turn_pulses (1–5 per trial, default 3). Configuration changes
invalidate the previous calibration receipt. Enabled avoidance requires
depth_plane and existing low-speed limits; drive also requires verified camera
sides, swept-body clearance and stopping on the actual mounting.

The matching Venom module advertises supported_protocol_versions including 2.
Pi uses frame protocol_version=2 only when avoidance is enabled, adding avoidance
and motion_phase (ready/turn_settling). Replies retain run/frame/sequence/revision,
model and TTL and allow go, stop, turn_left or turn_right. Unknown contracts,
stale identity, malformed evidence or invalid permits stop the trial.

The sequence is ZERO before obstacle, three consecutive clear side assessments,
bounded yaw-only turn, fresh capture after the local permit plus 100 ms settling,
then three new front CLEAR assessments before forward movement. Pi independently
requires a preceding zero submission, accepted policy/model, complete clear
selected-sector evidence, no recess and remaining turn budget. Existing motion
submission uses vx=0 and positive yaw for left, negative yaw for right.
Hardware mounting must verify actual yaw signs; pulse duration is not an angle.

Waiting and turns consume the original total 10-second trial and do not extend
ARM, watchdogs or the 0.1 SDK / 150 ms forward limits. Only ZERO is allowed while
waiting for a post-turn image. Global STOP, communication loss, executor errors
and manual takeover remain terminal. There is no automatic rearming or return
to the original heading.

This experimental feature still requires labelled left/right/both-side, thin
obstacle, recess and post-turn sequences plus operator-observed hardware
acceptance in both directions. Frontal camera coverage does not prove side/rear
clearance. Automated tests record mock callbacks and never contact motors.
Deploy matching protocol-v2 implementations in Pi and venom-module-rider.


## V3 forward corrections

Newly enabled avoidance explicitly selects avoidance.protocol_version=3 and
steer_left/steer_right. Pi submits low vx and bounded yaw in one existing motion
command. Legacy turn_left/right retain yaw-only semantics; saved policies without
an explicit maneuver version migrate to v2. Switching versions invalidates the
calibration scope and requires matching Venom support.

A v3 correction requires complete clear selected-sector, connecting-path and
near-guard evidence in the same current decision. These image-space masks are
approximations, not a measured metric footprint. No thresholds, forward limits or
watchdogs are relaxed. New nonzero commands require capture after the correction
pulse. No separate prior stop is required for v3. Three fresh front CLEAR frames
straighten motion; exhausted corrections without a clear path terminally stop
the trial with avoidance_no_progress, without rearming.

Combined vx/yaw behavior and changing camera pose still need physical acceptance.
Weak recorded box frames continue to yield UNKNOWN/STOP; no forced turn or
threshold tuning was performed. Robust ground reference and camera-pose
compensation remain follow-ups requiring better recorded scenes.
