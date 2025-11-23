# Resource diagnostics

This page explains how the control panel inspects and frees hardware resources
(microphone, speaker, camera, LCD) and how every action now flows through a single
resource-guarding workflow so the camera is always claimed just once.

## CLI tool

The existing helper continues to work:

```
./scripts/resource_diag.py status camera
./scripts/resource_diag.py release camera --pid 1234
```

- `status` returns JSON about the matched `/dev/*` paths, blocking PIDs, and the
  owning systemd units.
- `release` runs a dedicated helper (`scripts/sys_camera-free.sh` for the camera,
  `config/alsa/preflight.sh` for audio, `scripts/sys_lcd-control.py` for LCD) and
  now also calls `scripts/vision-resource-guard.sh release` to restore the preview
  services after the transfer.

## API / control panel

`/api/resource/<mic|speaker|camera|lcd>` exposes:

- `GET` → current inspection data. Internally `services.api_core.resource_diag.inspect`
  uses `lsof` and caches `ProcessInfo` per device.
- `POST {"action":"stop"}` → stops the systemd units that hold the resource using
  `services.api_core.service_diag.resource_stop`. Before stopping camera-related
  units we call `resource_diag.guard_camera("claim")` so `/dev/video0` is released
  once and for all.
- `POST {"action":"release"}` → runs the dedicated release scripts and calls the
  guard with `release`, so camera-preview services automatically restart afterwards.

The UI in `web/control.html` renders the diagnostic table with refresh/stop/release
buttons for each row. Every button communicates with this API, which, in turn,
delegates to the `resource_diag` module and the newly added `vision-resource-guard.sh`.

## Central guard integration

- `vision-resource-guard.sh` stops `camera-capture@raw.service`
  (or inne instancje `camera-capture@<mode>`) before `rider-vision-offload.service`
  starts, and przy zwalnianiu zasobów ponownie uruchamia odpowiedni tryb capture.
- `scripts/sys_control.sh` uses the guard when `/svc` is invoked for
  `rider-vision-offload.service`. This keeps all `/svc`/resource API pathways aligned
  and prevents multiple previews from fighting over `/dev/video0`.
- `resource_diag.guard_camera(action)` is the shared helper that both the API and
  the guard script can call, so stopping services and releasing resources always go
  through the same mechanism.

## Typical workflow

1. Operator opens the Control panel’s “Resource diagnostics” card.
2. They click “Stop service” → `/api/resource/camera` triggers `vision-resource-guard.sh
   claim` and stops preview units before the guard calls `rider-vision-offload`.
3. If the resource still appears busy, “Release” runs `scripts/sys_camera-free.sh`,
   and the guard script also restarts preview services afterwards.
4. Logs and UI show the updated holders, freeing the team from manual `lsof`/`fuser`
   guessing.

All diagnostic flows now rely on a single guard script, so locally running preview
services never collide with the offload pipeline.
