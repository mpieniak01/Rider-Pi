# Face studio and face runtime

Open `/face-studio` from the panel menu. Preview, author and explicitly play
face gestures using one renderer, animator and catalog. This feature sends no
motor commands and does not change arming.

## Workflow

Choose **Friendly**, **Simple** or **Original** styling. Preview, pause, scrub,
set intensity/tempo, and open the detailed pose editor when needed. Duplicate
built-ins or save custom gestures. Include a saved gesture in the robot set,
then **Save settings**. Saving never starts the LCD.

**Show on LCD** starts the face; **Stop face** stops only its worker and releases
its LCD resources. Other services are untouched. **Gesture preview** renders
the draft without hardware. **Active face** reads the existing worker's latest
image without another renderer or LCD takeover. This is a software image, not
proof of physical visibility or power. Camera/Device Info ownership is preserved;
busy or unknown LCD ownership blocks face startup.

Simulated speech is explicitly labelled and limited to the draft preview.
Runtime speech uses the normalized envelope of actually played audio through
the event API. Calling `speak(True)` alone does not synthesize mouth oscillation.

## Values and storage

The backend supplies all ranges, units, styles and expressions. The UI shows
milliseconds and percent: gaze, brows and smile −100…100, eyelids/mouth 0…100,
intensity 0…100%, tempo 50…200%. These describe graphics.

Editing the pose table reconstructs tracks on a common timeline. Original tracks
remain intact until that edit; displayed rounded values then replace them.
Changing expression sets its default pose in channels without authored tracks.

Custom gestures: `config/local/face-studio.json` (`FACE_STUDIO_LIBRARY`).
Runtime settings: `config/local/face-runtime.json` (`FACE_RUNTIME_SETTINGS`).
Both files are Git-ignored, written atomically and flushed. Pi stores the device's
active set; WSL drafts are separate. Import/export transfers are explicit.
Browsers poll shared settings; stale `if_revision` writes return 409. Use
**Reload settings** to resolve a conflict. Save/import operations start neither
LCD output nor physical movement.

## API — rider.face v1

| Endpoint | Purpose |
| --- | --- |
| GET /api/face-studio/gestures | Catalog, ranges, descriptors, settings and revisions |
| POST /api/face-studio/gestures | Save; optional id updates a custom gesture |
| DELETE /api/face-studio/gestures/&lt;id&gt; | Delete custom gesture and its active selection |
| POST /api/face-studio/frame | Draft PNG 240×240 at time `at` (seconds) |
| GET /api/face-studio/runtime | Worker state, settings, settings_revision, descriptors |
| POST /api/face-studio/runtime | Settings patch; optional if_revision |
| POST /api/face-studio/runtime/play | Explicit start: sink=lcd/file/null, expr, gesture_id, fps, duration_s |
| POST /api/face-studio/runtime/stop | Stop only the face |
| POST /api/face-studio/runtime/event | mood / gesture / listening / waiting / audio |
| GET /api/face-studio/runtime/frame | Latest active face image; 404 when stopped |

Gesture: `contract_version:1`, `name`, `expr`, `duration` (0.05–10 s),
`initial` (path → value), `tracks` (path → t0/t1/v0/v1/ease segments).
Versionless older gestures remain accepted. Expressions: neutral, calm, happy,
sad, curious, surprised, sleepy. Channels: eyes.dx, eyes.dy, eyes.blink,
brows.lift, brows.tilt, mouth.open, mouth.curve. API graphic values use −1…1
or 0…1, times use seconds. Easing: lin, in, out, in_out (smoothstep); original
preserves authored transitions. Limits: 32 segments/channel, 200 custom gestures,
64 KiB frame request. At 50% tempo playback can take up to 20 seconds.

Examples: `{"intent":"mood","expr":"happy"}`,
`{"intent":"gesture","id":"builtin:look"}`,
`{"intent":"audio","level":0.6,"playing":true}`.
Audio owns the mouth channel, with 80 ms attack, 140 ms release and automatic
closure after 250 ms without updates. Events require an active worker.
A provider-specific AI/audio integration is outside this PR.

Legacy /face/play, /face/stop, /face/state, /face/render and /api/draw/face remain.
Direct FaceController callers retain legacy styling by default; Studio/shared
runtime default to friendly.

## Resource and display lifecycle

Direct PIL/RGB output removes per-frame PNG encode/decode. One worker holds at
most seven channels; newer intents replace older ones. Idle has low priority
and returns to the emotion's resting pose. The worker keeps one current image
and lazy PNG; draft previews have an LRU of 16 PNGs and one rendering slot
(429 with Retry-After when busy). Unchanged images are not resubmitted to LCD.
File output writes the first diagnostic snapshot, not every frame to SD.

Operator-selected **battery** mode caps output at 6 FPS, reduces idle gestures
and stops after 45 seconds without intent/audio. **Cable** caps at 12 FPS
without automatic idle expiry. A 100% battery reading is not a cable detector.
Hidden browser tabs stop frames, polling and timers.

LCD orientation remains **270°**. A 240×240 face is centered in the physical
240×320 submission. The existing IP/battery startup screen is preserved.
Hardware opens only after ownership checks; shutdown closes owned descriptors
and rechecks ownership before powering off. No global GPIO cleanup is used.

Hardware-free measurement: `python scripts/face_benchmark.py`.
Prior-code comparison:
`python scripts/face_benchmark.py --baseline-ref 354cfddccb7602de4e642d0f454af8f6821364ef`.
The report separates render/RGB565, single-core CPU at 12 FPS and RAM.
Process RSS includes dependencies; loop allocation growth does not measure energy.
Runtime exposes render and submission times for changed frames.
Device results: [performance report](FACE_PERFORMANCE.md).

## Character shells

The **Character** selector is separate from the eye style: No character,
Freckles, Kitten, Little robot and Professional. No character remains the default and
preserves the previous image. The character shells add a head, ears and hair or
an antenna; the same animated eyes, brows and mouth are drawn on top.

The optional `skin` setting is persisted on Pi with the other face settings.
Studio sends it for draft preview and runtime loads the same saved value.
Saving it does not start the LCD. A skin changes appearance; it does not
change emotion, robot movement or behaviour. Gesture import/export stays
independent of the current character.

Descriptors expose `skins` with stable IDs and PL/EN names. Older settings
without `skin` use `none`; invalid IDs are rejected. Background geometry is
cached once per skin/style change. The existing three preview renderers and
16-frame PNG cache remain bounded; there are no new image packages or files.


The Professional character uses its own adult facial proportions: a smooth
oval, almond eyes, restrained brows and mouth, a subtle nose and hair, without
cartoon blush. All seven emotions, blinking, gaze and the audio-envelope hook
use the shared animator. It is a visual variant, not a separate personality
or speech provider. Eye styles tint the character; its adult geometry is
retained in every style. Only the static shell is antialiased and resized
once on selection; frames are drawn directly at LCD resolution.
