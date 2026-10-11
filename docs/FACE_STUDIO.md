# Face studio

Open `/face-studio` from the panel menu to preview and author face gestures
without LCD hardware. It uses the production `FaceRenderer` and `Animator`;
it never opens UART/SPI, controls motors, or takes LCD ownership.

Choose built-in blink, gaze or expressions; play, loop, pause, scrub and save
a PNG frame. Create or duplicate a gesture, then add timed poses in milliseconds.
The first pose is the initial state. Gaze and brows use −100…100; eyelid closure
and mouth opening use 0…100. These are graphic parameters, not robot motion.
Save new gestures or update/delete custom ones. Built-ins remain read-only.
Import creates a draft; save to persist. Export includes the complete gesture.

Editing the pose table rebuilds transitions between poses on a shared timeline.
Original built-in/imported tracks remain intact until the first table edit.
Displayed pose values are rounded; editing intentionally reconstructs tracks.
One expression applies to the whole gesture.

## Storage and endpoints

Custom gestures are atomically saved on the panel server in
`config/local/face-studio.json`, ignored by Git. Override using
`FACE_STUDIO_LIBRARY`. WSL and device instances have separate libraries;
transfer gestures explicitly through import/export.

- `GET /api/face-studio/gestures`: library and parameter ranges.
- `POST /api/face-studio/gestures`: save; optional `id` updates a custom gesture.
- `DELETE /api/face-studio/gestures/<id>`: delete a custom gesture.
- `POST /api/face-studio/frame`: PNG 240×240 at `at` seconds.

Specification: `name`, `expr` (neutral/happy/sad), `duration` (0.05–10 seconds),
`initial` (path → value), `tracks` (path → `t0/t1/v0/v1/ease` segments).
API values use −1…1 or 0…1. Allowed paths: `eyes.dx`, `eyes.dy`, `eyes.blink`,
`brows.lift`, `brows.tilt`, `mouth.open`. Easing: `lin`, `in`, `out`, `in_out`.
Limits: 32 segments per track and 200 custom gestures. Invalid values are rejected.

The browser requests up to about 12 frames/second with only one request in flight.
Hidden tabs stop playback and frame requests. No permanent server rendering loop
is started. Pause freezes pupil drift too. Preview is upright; physical LCD
orientation/270° compensation is unchanged. This is not a live LCD mirror.
Saving does not automatically activate a gesture in robot behaviour.
