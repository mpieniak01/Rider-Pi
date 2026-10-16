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
snapshots already in display orientation declare zero rotation.

Pi preserves the existing RAW orientation default: an unset or empty PREVIEW_ROT
means 0 degrees. Explicit PREVIEW_ROT and flip settings are retained. The LCD
mounting compensation is separate and does not choose the camera orientation.

No software JPEG re-encode is required on Pi solely to rotate a native stream.

Pi computes frame_age_ms at send using its capture monotonic clock. Picamera2
snapshots and hardware MJPEG use sensor capture time. An OpenCV-only reader uses
the beginning of its blocking read and explicitly reports unknown driver-buffer
age in status; this does not claim a measured sensor exposure timestamp. Venom adds only
elapsed time measured on its own clock; it never subtracts clocks from different
hosts. A Pi-status capture/age anchor and the full request round trip provide a
conservative age bound for queued transport, both on Venom and in the browser.
Missing or mismatched anchors cannot be presented as fresh native input.
Receipt, file mtime, reconnect, overlay rendering and cache hits do not renew
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

Before a native observation/trial, Pi waits for the current session's first fresh
RAM source within a bounded preparation operation, then calls
`/compute/vision/status?stream=true` to prepare ingest without motion or inference. A cold producer reports ready=false; an actual
failed producer remains an error. Preparation forces a current profile read, so a
previous session cannot satisfy the handshake.
The returned stream.ready/latest_source identifies a source already available on
Venom. Pi checks its own session/epoch/revision and original capture age. Preparation
happens before any existing trial authority handoff.

`POST /compute/vision/decision-reference` accepts frame (the existing versioned
VisionFrame policy/run envelope) and source (camera_session, sequence,
transport_epoch, pipeline_revision, frame_id, sha256). Venom resolves the exact
bounded, short-lived source; no JPEG is uploaded again. A model result may be
shared for the exact source and model/policy input, while every run still evaluates
its own sequence, clear count and permission gates. Pi verifies returned evidence
and final capture-to-response age before actuation. The VisionFrame frame_id and
sequence identify the request and its run; source.frame_id and source.sequence
identify the camera capture. They need not be equal. Preview correlates all six
source reference fields with the image headers, while preserving request/run
fields for Pi's response checks. A lost Venom link never activates a local
fallback or reuses an old permission.

For an authenticated Pi decision-reference request, the decision age is the
maximum of Pi-reported relative capture age plus host time since admission, and
the part's original send age plus its residence on the host. The status-anchor
upper bound includes HTTP roundtrip uncertainty; it remains the preview/cache
bound and must not be used as an exact motion deadline. This distinction never
renews a source: a buffered part or a Pi-reported age already at the deadline is
rejected, as are mismatched identities. Pi independently checks its original
captured_monotonic_ns deadline at response admission and immediately before motor
submission; a host GO cannot extend the 300 ms capture budget.

Reference replies include source_timing_ms: pi_reported_age,
host_before_inference, observed_age, upper_age and deadline_age. These diagnostics
expose timing uncertainty separately from the decision budget; they grant no
motion permission.

## Paired rollout

The implementation is delivered together in [Rider-Pi #280](https://github.com/mpieniak01/Rider-Pi/pull/280)
and [Venom Rider module #18](https://github.com/mpieniak01/venom-module-rider/pull/18).
Venom core uses its existing optional-module interface; no core code change is required.
Update the Pi runtime and module as a pair, then verify source identity and passive
observation before operator motion acceptance. Snapshots and DA2 remain the default
for a previously unconfigured installation. Native MJPEG is an opt-in transport;
short tests and lower CPU alone do not establish equivalent obstacle accuracy.

For a transport rollback, stop the loop and camera, select Venom + snapshots in
either panel, and start passive observation. This preserves the existing model and
motion limits. Configuration never restores a previous autonomous drive. Missing
SSD/TFLite assets remain unavailable capabilities rather than an installed fallback.

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

## Operator preview and measurement history

In Venom's processed view, L (cyan), C (white STOP boundary) and R (violet)
identify the regions used by that displayed analysis. Image-space regions use the
actual configured corridor and its adjacent side regions, not thirds of the whole
image. Ground mode shows projected paths. Incomplete or unavailable geometry is
marked uncertain. The orange dashed editor is an unsaved draft; moving it does not
relabel the analysis already attached to an image.

The visible JPEG and its capture metadata remain paired until the next image has
loaded. Text cards sample the latest decoded L/C/R assessment once per second for
readability, so they can briefly lag the live image. Each sample retains its capture
identity. The image and authoritative motion decision keep their normal cadence.
Invalid source data or a changed camera, model or policy immediately invalidate the
previous sample. Snapshot and native MJPEG use the same presentation rule. The
image keeps its original freshness deadline and stale-input alerts remain visible.
Preview labels do not grant motion permission. The operator ARM and global STOP
toolbar remains visible while scrolling.

The Pi overview retains CPU/RAM history with original measurement timestamps after
a failed read and shows the read error and measurement age. Its window advances
through the last 60 seconds on Pi's timeline, including during an outage. Old
points expire and gaps remain visible; the panel does not stretch sample indices,
insert zero measurements or refresh the age of a stopped series.

Camera session and frame identifiers contain only ASCII letters, digits, underscores and hyphens (1–160 characters), with no CR/LF. The shared stopped-status example lists the effective-stage names emitted by Pi.
