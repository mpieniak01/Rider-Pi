# Perception provider and model

The Rider-Pi navigation panel separates the image analysis provider from its
model. Reading or selecting never starts motion. A camera that was off stays off.

## Configuration ownership

| Information | Source of truth |
| --- | --- |
| `local` / `venom` provider, local engine, image transport | Existing `data/camera_pipeline.json`, `profile.analysis_location/local_engine/remote_transport` and its `revision` |
| Venom weights, installation, availability, loaded model | Rider module catalog and runtime on the Venom host |
| Selected host model and artifact fingerprint | `data/navigation_config.json`, `perception.model_id/artifact_sha256` and configuration revision |
| Motion authority | Existing Pi motion executor, current ARM and separate acceptance |

Pi stores neither a Venom catalog copy nor its weights. Selecting the image
provider does not change voice or text routing. Both panels read the same Pi
configuration; the Pi panel refreshes automatically. Selected and active are
separate facts, including when the camera is off or the host is unreachable.

Local options reuse the existing camera pipeline: `local-canny` (OpenCV,
no weights), `local-ssd` (MobileNet SSD), and `local-tflite` (EfficientDet Lite0).
Discovery reads the actual files configured by `SSD_MODEL_DIR` and
`TFLITE_MODEL` and existing capabilities, without installing packages or loading
models. Canny computes edges; SSD/TFLite detect objects. They do not provide
floor segmentation or claim compatibility with the host navigation contract.
Existing local autonomous scenarios remain in their current applications and
retain their safety contracts.

## API

Responses support the existing `rider.navigation_loop` envelope, version 1.

- `GET /api/navigation/models`: fresh Venom catalog through the selected compute
  endpoint. An unavailable host returns an error, never an old ready catalog.
- `GET /api/navigation/local-models`: local engines, availability, basenames and
  fingerprints without private paths; selected/active local model, provider and
  pipeline revision. It never calls Venom.
- `POST /api/navigation/model`: `{"revision": 7, "model_id": "segformer-b0-ade20k"}`.
  Forwards operator intent to the host. The host qualifies the artifact;
  the client cannot supply an arbitrary URL, path or fingerprint.
- `POST /api/navigation/model-selection`: internal host commit:
  `{"revision": 7, "model_id": "segformer-b0-ade20k", "artifact_sha256": "<64 hex>", "engine": "segformer"}`.
  Atomic CAS returns `{ok,persisted,config}`.
- Provider and local engine still use `POST /api/resource/camera/pipeline`,
  `action=configure`, current `expected_revision`, fresh `request_id`, and the
  complete existing profile.

The proxy uses only configured compute credentials and origin:
`GET /api/v1/rider/compute/vision/models` and
`POST /api/v1/rider/compute/vision/model`. Credentials remain server-side.
Catalog reads never persist inventories or start installation.

## Selection and safety

Disarm and stop S14/S15 loops and moving tasks before selecting a model, provider
or local engine. Camera-only preview may stay active. Missing/stale executor
status or an untrusted goal journal cannot prove idle. Refusal never stops
services implicitly.

Selection reuses the existing goal transaction and the settings mutex shared
with the sole motion executor. Concurrent ARM cannot enter the write transaction;
STOP/EStop bypass the mutex. Every actual change clears `verified`,
`calibration_id`, approved `model_sha256`, and `sweep_verified`, setting
`mode=observe`. Host model selection does not restart the camera. Changing
provider/local engine may rebuild the camera pipeline, preserving only existing
passive camera demand, without restoring analysis or control.

Ordinary `/api/navigation/config` cannot replace or remove explicit model
identity. Explicit semantic selections (SegFormer, Fast-SCNN, YOLO semantic)
are observation-only, also at the final Pi permit gate. Depth Anything V2 needs
a separate acceptance of the exact selected artifact before driving. Legacy
configurations without identity fields retain their existing behavior.

Requests carry explicit ID and SHA in `perception`. Replies must confirm that
identity, configuration revision, run, frame and sequence; mismatches reach
neither current results nor actuators. Repeating a commit after a lost ACK is
idempotent while identity and cleared acceptance remain identical. Other stale
revisions conflict; clients refresh state without automatic mutation retries.

## Restore and acceptance

On current code, reselect the previous ready model and, if needed, the previous
camera profile with current revisions. Restore remains observational and does
not restore motion permission. Before downgrading to Pi code that rejects new
fields, remove optional identity in a controlled transaction after stopping
loops and confirming DISARMED. Never restore an old approved driving policy.

Automated tests use temporary files, fake transport and memory-only motors.
Operator acceptance checks both panels, camera OFF/ON, selection refusal during
control, and removal of old results on a switch. Motion needs separate operator
consent for a specific trial.

## Local image identity

Managed `/camera/proc` reads only processed RAM frames, without falling back
to older JPEG files. The actual producer attaches `local_engine`,
`model_id=local-<engine>`, and `analysis_location=local` to the same capture
metadata (session, epoch, revision, capture time). The API rejects a prior
configuration or another engine. `X-Rider-Source-Json` preserves those fields;
`X-Rider-Local-Engine` and `X-Rider-Local-Model-Id` project them as headers.
RAW carries no model identity. Closing the producer empties the buffer.
The panel also rejects replies from an earlier session/epoch, including
restarts of the same profile. HTTP read time never replaces capture time.
