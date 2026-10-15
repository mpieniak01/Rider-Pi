# Directional navigation contract

The paired Venom module provides editable image ROI and sensitivity plus optional
bounded steering. Pi owns the existing revisioned navigation policy and remains
the sole motor executor. Saving settings never starts motion or arms the robot.
Avoidance is disabled by default; v1 forward-only behavior stays available.

## Versioned actions and admission

Protocol v2 keeps STOP then yaw-only turn_left/turn_right. Explicit protocol v3
uses steer_left/steer_right: existing low vx and bounded yaw in one submission.
Old enabled policies lacking a maneuver version migrate to v2. Policies without
geometry migrate to image mode rather than silently gaining a new projection.
V3 image mode remains the legacy mask approximation; ground mode is opt-in for
an existing installation.

Every nonzero reply must match run, frame, sequence, revision, model and current
capture budget. A correction requires three clear side samples, a clear selected
path and near guard; Pi independently validates the evidence. Captures from
before/during a correction cannot authorize subsequent motion. The host holds
the chosen side until fresh front clearance straightens the trajectory.

Original 10-second ARM/trial, feedback watchdog and pulse limits remain:
forward <=0.1 SDK / 150 ms, yaw 0.01–0.1 SDK / 50–150 ms.
No implicit re-ARM or extension is introduced. Terminal avoidance_no_progress
cannot resume on a later GO.

## Ground projection policy

avoidance.geometry contains mode (ground/image), normalized camera fx/fy/cx/cy,
radius_ratio, lookahead_ratio and max_heading_deg. New defaults keep avoidance
off and leave fx/fy/radius_ratio empty. The policy validates finite ranges;
drive mode with enabled v3 ground geometry requires these calibration values.
The lease also rejects nonzero replies with missing configured projection,
incorrect geometry type, invalid ground normal/height or insufficient support.

fx/fy are focal lengths divided by delivered image dimensions; cx/cy are its
normalized principal point after actual resize/crop/rotation. The pinhole path
needs characterized/corrected lens distortion. radius_ratio is the conservative
circumscribed body radius divided by the minimum accepted physical camera height.
The radius must include all body points relative to the camera ground projection
across accepted poses, plus margin. lookahead_ratio uses current inferred ground
height units; these values do not claim centimetre measurements.

The host fits robust ground from each single depth inference, projects inflated
capsules over 49 headings and extracts contiguous free gaps. It checks observed
thin obstacle points and recesses in addition to sampled rays. The preview shows
projected paths; incomplete FOV coverage is UNKNOWN. Ground mode uses these
settings instead of an image ROI for its path.

Camera pose comes from the current ground plane, not measured IMU/height.
Large reference changes reset stability, never the correction budget. A fresh
comparable observation measures normalized clearance gain after correction.
max_stalled_corrections (1–5, default 2) and progress_min_delta (0–0.3, default
0.03) control stagnation; max_turn_pulses (1–5, default 3) is an independent cap.
Only the original valid session can wait at ZERO for uncertain projection;
communication loss and operator/global STOP remain terminal.

Full heading candidates stay in optional host diagnostics, not the Pi response.
The selected paths, reference and counters fit the existing body/header bounds.
A direction selects a bounded correction side, not a calibrated metric yaw or
certified trajectory; physical combined-command sweep/braking remains to accept.

## Tests and outstanding data acceptance

Automated tests exercise actual lease and runner code using recorded callbacks,
never hardware. They cover malformed ground evidence, missing calibration,
legacy migration, pulse/TTL limits, terminal STOP and cross-repository replay.
The mobile control-camera layout fix is included in this branch.

The next data PR records calibrated camera/body geometry and timestamped held-out
sequences for floor, left/right/central/both obstacles, thin objects, recesses,
low light, varying height/pitch/roll and fresh post-correction frames. Verify
actual yaw sign, footprint, motion and braking; score false GO/STOP, flicker,
side errors and latency. Weak historical box recordings are negative examples,
not proof that a physical passage is free. No thresholds are relaxed to force
their result. Monocular depth and unseen lateral/rear space remain limitations.
