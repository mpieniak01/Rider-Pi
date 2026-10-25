# Visual image reference

The reference on the navigation image is a Pi-owned visual measurement aid,
independent of drive approval, model thresholds and camera calibration.
`purpose=visual_reference_only` does not qualify metric collision geometry.
Saving it never sends a posture command, moves the robot, starts observation
or grants ARM. A lowest-pose reference describes an operator measurement;
it does not command that pose.

## Persistence and API

`GET /api/navigation/image-reference` returns version=1, revision, values
and purpose. Before the first save, revision=0 and values=null.
`POST` accepts exactly `{revision,values}`; a successful atomic write
increments revision and returns the saved state. An old revision returns 409
image_reference_conflict, invalid data 422 image_reference_invalid, and storage
failure 503 image_reference_persistence_failed. Corrupt stored data is not
silently replaced by defaults.

With negotiated API v1, the save operation confirms configuration_persisted,
reports the saved revision, actuation=false and physical_completion=not_applicable.
HTTP success confirms storage, not measured physical accuracy.

Default storage is data/navigation_image_reference.json; RIDER_IMAGE_REFERENCE
selects another operator-managed path. It has its own lock/revision, independent
of the navigation policy transaction.

## Values

| Field | Meaning and bounds |
| --- | --- |
| visible | Boolean overlay visibility |
| frame_size | Two integers: width 32–1280, height 32–720 |
| track_width_cm, robot_width_cm, camera_height_cm | Finite numeric values 0.1–1000; robot width cannot exceed track width |
| left_edge, right_edge | Two normalized [x,y] points per edge, values 0–1, ordered from upper to lower image row |
| markers | 2–8 [distance_cm, normalized_y] pairs; distances 0.1–1000 increase while image y decreases |
| reference_pose | Exactly lowest |

Corresponding edge rows must match within 0.000001; right x must exceed left x
by at least 0.01 at both rows. Unknown fields, booleans used as numbers,
non-finite values and invalid ordering are rejected. Field definitions live in
[services/image_reference.py](../services/image_reference.py).

Refresh after a revision conflict and review the new state before applying
another draft. Do not derive centimetres from a depth residual or confidence.
[Navigation visualization](NAVIGATION_VISUALIZATION.md) ·
[Calibration](apps/calibration.md) · [Policy parameters](vision-policy-parameters.md).
