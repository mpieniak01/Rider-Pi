# Venom compute and perception

Pi owns camera, audio, calibration and motion. In S12/S13, the paired Venom module
performs text, STT/TTS and scene description. Scene description is neither an
obstacle detector nor motion permission. Those task results are not routed to
actuator commands. S14/S15 use the separate bounded navigation loop described
below. Optional chat tools controlling the robot belong to R3.

## Configuration and transport

`data/compute_config.json` (mode 600) stores executor selection, address, tasks
and revision. `config/compute.example.json` starts with the executor OFF. The
private `/etc/default/rider-compute` supplies `RIDER_COMPUTE_TOKEN` to the API,
voice and image offload services. Match device ID/token in the Venom module;
never publish credentials or device-specific configuration.

```sh
python3 -m services.compute_config --url https://venom-host:8443 --device-id robot
```

This saves configuration; it does not start a goal. Use
`GET /api/compute/config` and `POST /api/compute/config` with
`{"executor_id":"venom","revision":<observed revision>}` to select the executor.
`null` disables new remote computation. Stop compute goals before changing it;
409 means a revision conflict or an active goal. CLI and API share the
orchestration lock. PC heartbeat does not change selection/address, and a Venom
failure does not start local models.

Authenticated transport requires HTTPS with certificate verification or an
HTTP loopback endpoint behind SSH (`localhost`, `127.0.0.1` or `[::1]`). LAN HTTP
is rejected by the transport client. Configure TLS/tunnels separately before
hardware acceptance. The URL accepts a host base or `/api/v1/rider/compute`.
Tunnel ports are installation settings, not additional public service ports.

## Compute goals

- **S12 — scene description:** existing RAW capture/feed and a lightweight
  client send JPEG/PNG without decoding/re-encoding on Pi. A two-frame receiver
  queue selects the newest frame. Capture time comes from completed camera
  read, before processing; it is not sensor exposure time. A sidecar binds time
  to file identity; missing matching metadata is explicitly `file_mtime`.
- **S13 — conversation:** microphone/listener, Whisper, the selected response
  runtime, Piper WAV and the existing Pi player. No motion NLU/tools or local
  voice-web/model are started. The microphone closes before inference.

Stopping a goal closes its subscriptions, HTTP, microphone/player and session.
Other goals retain their sessions. Shared capture stops only after its last
consumer releases it. Running goals do not need an open browser.

Single tasks use `POST /api/compute/tasks/<task>` with binary input and
`X-Rider-Params: {"language":"pl"}`. Synthesis returns WAV, other tasks JSON.
The same client is available without starting hardware:

```sh
python3 -m apps.compute capabilities
python3 -m apps.compute text --text 'Reply briefly in English'
python3 -m apps.compute tts --text 'Hello' --output /tmp/rider-voice.wav
```

TTS CLI writes a file without playing it. Physical recording/playback requires
an explicit goal or operator command; automated tests use mocks.

`GET /api/compute/status` reads bounded local snapshots. Readiness is per task
in `capabilities.tasks`. Inference time includes cold model loading; it is not
a separate load-time measurement. Voice records the actual `response_task`:
`text.respond` for R2 or optional `conversation.respond` for R3. A stopped goal
is OFF. Match TTS language to the selected Piper voice.

Compute v1 binds device/boot identity, separate voice/vision sessions, input and
result correlation, TTL up to 60 seconds and a bounded queue. Stale results,
restart, model change and OFF do not replay jobs. Transport, saturation and
unready models return explicit errors. The module owns its `docs/COMPUTE_V1.md`.

## Navigation loop — S14/S15

Pi owns revisioned `data/navigation_config.json` and
`GET/POST /api/navigation/config`. POST supplies `revision` and `values`; saving
does not start services. The `/navigation` panel and paired module share it.
S15 observes using capture, transport and Venom segmentation without ARM or
motion/STOP publication. S14 drive requires an accepted stopping area,
calibration ID/model hash, separate operator ARM for navigation and explicit
start. It never automatically rearms or resumes.

Venom's separate ONNX SegFormer is not an LLM or a metric distance sensor.
Acceptance depends on camera mounting, floor, lighting, speed and model; scene
or configuration changes require reassessment. Transparent obstacles and step
edges are not guaranteed detections. See [directional navigation](DIRECTIONAL_NAVIGATION.md).

Pi independently checks correlated replies and bounds each pulse. The image
`decision_deadline_monotonic` prevents stale frames from sustaining motion;
`decision_feedback_deadline_monotonic` bounds waiting at zero output for the
next reply, to at most 500 ms. Neither extends the original ARM/trial (at most
10 seconds). Missing feedback, model/config/arming changes, invalid identity,
dark/stale frames and transport failure end the trial. Heartbeat grants no motion.
A valid reply with less than 50 ms pulse budget produces ZERO and waits for a
fresh reply under the original deadlines; it does not extend the old GO.

Observation permits up to 1 second HTTP read timeout and skips stale frames,
ending after 5 seconds without a usable frame. Drive waits up to 5 seconds for
its first fresh frame at startup, without output; subsequent drive frames keep
the strict configured budget. Preparation distinguishes 15-second service
setup from the 5-second post-ARM start budget and reports request identity plus
`phase_timings_ms`. These budgets do not renew permission to move.

`/run/rider-motion/navigation_loop.json` and goal state expose observations,
not proof of current physical conditions. Units use `Restart=no` and stay out
of boot/minimal profiles. Automated tests use mocks only. Acceptance of a
calibrated scene does not establish metric stopping distance or universal
perception quality. Deploy the matching Pi/module/core and validate actual
camera/audio separately; keep device test data and logs in local operational notes.

[Polish guide and acceptance context](../docs_pl/COMPUTE_VENOM.md)
