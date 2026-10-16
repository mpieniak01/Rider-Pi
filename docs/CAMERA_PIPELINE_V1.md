# Camera pipeline v1

This interface is shared by Rider-Pi and the Venom Rider module. Pi owns the saved
profile, revision, camera lifecycle and motion policy. Venom owns remote inference.
The machine-readable definitions and synthetic examples live in
`config/contracts/camera_pipeline_v1.schema.json` and the adjacent examples file.

## Profiles and lifecycle

Pi exposes GET/POST `/api/resource/camera/pipeline`; Venom proxies it at
`/api/v1/rider/camera/pipeline`. GET reads state without opening a camera or loading
a model. POST accepts contract_version=1, request_id, expected_revision and action.
Configure requires a complete profile; start/stop forbid the profile field.

A profile contains analysis_location (local or venom), local_engine (canny, ssd,
tflite) and remote_transport (snapshots or mjpeg). The inactive branch is retained
as the operator's next choice. Capability lists report engines actually available
on that Pi; they are not a promise that every installation has every model.
Local processing does not produce autonomous GO. Manual motion remains independent.

Pi persists the profile in data/camera_pipeline.json (RIDER_CAMERA_PIPELINE_CONFIG
overrides the path). Runtime state and the bounded Unix socket live in
/run/rider-camera (RIDER_CAMERA_PIPELINE_RUNTIME). Defaults preserve venom/snapshots
without starting any camera. Revision starts at 1 and changes only with a profile
change. Repeating a request ID and identical payload is idempotent; reusing it with
a different payload is a conflict. Stale expected_revision, incompatible activity
and busy transitions return 409. Malformed requests return 400; unavailable runtime
returns 503. The response exposes saved profile, active_profile, state, actual
effective_stages, consumers, transport_epoch and latest source metadata.

Changing a profile stops the old observation through the existing domain manager
and waits for idle before starting its replacement. A conflicting manual/foreign
motion owner is not taken over. This interface never arms the robot. Keep the three
existing STOP meanings: motor zero, loop plus camera termination, global disarm.

## One producer and explicit stages

Only one process owns the camera. Local filters use its raw RAM buffer. Native
MJPEG uses the camera/hardware encoder and bounded RAM IPC, without writing
periodic JPEG files or running the legacy frame distributor. The API is a reader,
not another camera producer. The optional local processed preview is encoded only
when requested. A local profile does not start Venom inference. Starting an explicit
RAW/sample reader is a separate consumer, not an automatic second inference path.

Pi's `/api/resource/camera/stream.mjpg` returns multipart JPEG. Each part has
Content-Type, Content-Length and X-Rider-Source containing the source JSON.
`/api/resource/camera/frame?view=raw|proc` returns the current RAM JPEG.
Slow readers discard intermediate frames; queues and reader counts are bounded.
Capture sequence advances even when encoded pixels happen to be identical.

## Source identity, orientation and freshness

Source fields are contract_version, camera_session, sequence, transport_epoch,
pipeline_revision, frame_id, sha256, frame_age_ms, captured_monotonic_ns,
encoded_width, encoded_height and image_transform. Frame ID is the camera session
followed by a dash and sequence. SHA256 identifies the original encoded bytes.

Image_transform specifies the clockwise rotation still to apply on Venom, then
horizontal/vertical flips. It is applied once before inference and display. Legacy
snapshots already in display orientation declare zero rotation. No software JPEG
re-encode is required on Pi solely to rotate a native stream.

Pi computes frame_age_ms at send using its capture monotonic clock. Venom adds only
elapsed time measured on its own clock; it never subtracts clocks from different
hosts. Receipt, file mtime, reconnect, overlay rendering and cache hits do not renew
source freshness. Missing/stale source, changed epoch/session or timeout yields
unknown/STOP under the existing policy. Display freshness and motion deadline are
separate: this change does not extend the Pi motion lease or 300 ms deadline.

## Venom stream and decision references

Venom exposes `/camera/stream/raw` and `/camera/stream/venom` under its rider API.
A shared ingest serves preview and decision consumers. Browser parts retain
X-Rider-Source as pi-camera/venom for compatibility and carry the complete source
JSON in X-Rider-Source-Json; source age/session/epoch/revision also have explicit
headers. Processed parts carry X-Rider-Analysis-Json tied to that same source.
A browser uses streaming OR snapshot polling for a selected preview, cancels the
old reader on changes and keeps the original age on decode, freeze or disconnect.

Before a native observation/trial, Pi calls
`/compute/vision/status?stream=true` to prepare ingest without motion or inference.
The returned stream.ready/latest_source identifies a source already available on
Venom. Pi checks its own session/epoch/revision and original capture age. Preparation
happens before any existing trial authority handoff.

`POST /compute/vision/decision-reference` accepts frame (the existing versioned
VisionFrame policy/run envelope) and source (camera_session, sequence,
transport_epoch, pipeline_revision, frame_id, sha256). Venom resolves the exact
bounded, short-lived source; no JPEG is uploaded again. A model result may be
shared for the exact source and model/policy input, while every run still evaluates
its own sequence, clear count and permission gates. Pi verifies returned evidence
and final capture-to-response age before actuation. A lost Venom link never
activates a local fallback or reuses an old permission.

## Compatibility and access

The existing snapshot endpoints and local engines remain available. Older Pi
versions return a clear supported=false proxy result; they are not represented as
a valid v1 status. There is no silent fallback from native to snapshot after error.
Pi media/config routes use the current camera/resource API trust boundary; no
motion token is placed in media URLs. The Venom proxy uses its existing device
session for mutations; compute reference endpoints keep existing compute
authentication. Public deployments must retain their configured upstream access
control.

Contract examples are synthetic protocol fixtures, not physical acceptance data.
An encoder ACK, green overlay or passing mock test is not proof of physical motion.
