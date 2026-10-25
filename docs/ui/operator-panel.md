# Operator panel

The panel uses one catalog: `GET /api/logic/catalog`, version 2. Tasks,
domain options, service members and resource consumers come from the API.
A missing or older catalog enables observation and blocks starting tasks.

## Views

| View | Information and actions |
| --- | --- |
| Overview `/view` | Complete Rider-Pi dashboard: system, devices, CPU/RAM history, BUS health, obstacle and ROI histogram, RAW/PROC/OBST/TRACKER, API metrics and frame ages. Tasks and blocks supplement measurements. |
| Tasks and control `/control` | Catalog, explicit operator consent, short pulses, actuator capabilities, requests and ACK. |
| Devices `/devices` | Process owners, task consumers, camera, audio, LCD and UART. Image preview on demand. |
| System `/system` | Services and dependencies. Administration explicitly enabled in the current tab. Separate autostart changes. |
| Navigation `/navigation` | Map, pose, data age and quality; explicit start/return requests and configuration while DISARMED. |
| Chat `/chat` | Selected AI domain and optional TTS. Sending explicitly prepares the required domain. |

Viewing pages, cards, provider lists or refreshing data never starts services
or actuators. Selecting an option does not start a task. Task buttons and
message sending are separate, explicit requests.

## Complete measurements dashboard

The heading names the device and Overview. Measurement cards, both charts
and all four image previews remain visible without opening details or
navigating to System. The layout uses four columns on wide screens, two
on smaller screens and one on phones. Safety, task catalog and calibration
changes preserve these functions.

`/sysinfo` provides flat CPU, 1/5/15 minute load, memory, disk, temperature
and history fields. API fields named MB/GB mean MiB/GiB. History contains
at most 60 samples, not a guaranteed 60 seconds. Missing chart values form
gaps; zero remains a measurement. The chart covers the last 60 seconds of
server-aligned time, not 60 seconds ending at the last received sample.
A failed read keeps the known history and its original timestamps, displays
the read error, and ages the points out of the window. It does not reset the
graph or make old measurements fresh. The caption reports the actual sample
count, covered interval and gaps. The demand-driven sampler sleeps after
30 seconds without readers, so reopening the panel can require rebuilding
history; no readings are fabricated for that interval.

`/state.devices.xgo` supplies IMU and battery observations; `on` is not
required. Source ages and flags determine usability. Channels in
`safety.sensor_quality.sensors` retain independent times and quality:
battery there is a 0–1 ratio, whereas `battery_pct` is already percent.
IMU orientation is not robot position. Raw SDK yaw is shown separately
with its unverified physical semantics. `healthz: ok` confirms API
availability, not every sensor's health.

Overview reads telemetry every second and other measurements and image metadata about every 2 seconds.
`/vision/snap-info?light=1` uses file statistics without reading images to
compute MD5. Previews fetch only fresh frames from an active camera.
Disabled cameras, missing images and old cache are explicitly labelled.
Opening the dashboard starts no producer or task. System shows its basic
measurements before the service list; source JSON stays in details.

## Motion and acknowledgements

`GET /api/control/state` supplies `safety.contract_version = 1`. Missing fresh
state, UNKNOWN, wrong owner, expired permission or unverified actuator
`available`/`stop_verified` blocks motion. DISARMED and ESTOP have
`read_only: true`; explicit ARM and clearing ESTOP use separate preparation
rules. ARM also requires hardware_ready and ready. Clearing ESTOP returns to DISARMED.

ARM needs a specific plan, confirmation that the robot is prepared, a selected
owner. Manual panel ARM uses arming_mode=operator without a timer; timed
test/navigation sessions keep their bounded lease. Opening a view or reconnecting never
automatically arms. With wired power, the operator must provide clear space
and secure the cable. Navigation and System provide the same explicit
preparation controls for their task context. Changing views does not disarm
the manual operator session; a held gesture ends on release/focus/page loss.
A new page must read fresh state and respect the bound panel identity.

Every actuator, ARM or clear request creates one envelope: `request_id`,
`generation`, increasing `seq`, `source`, `ts`, `ttl_ms <= 500`. Mutations are
never automatically retried or given refreshed metadata. A manual pulse is
resolved from Pi settings, currently 0.01–1.0 s (default 0.25 s).

The API's `server_time` is separate from measurement `observed_at`. The panel
aligns its clock during safety reads: command time uses the lower network
latency bound, while observation age uses the upper bound. An unconfirmed
clock or RTT above 500 ms blocks new movement commands. STOP is independent
of clock alignment.

Request history is separate from executor state. `pending` means waiting.
Only an exact terminal ACK changes a request to `executed` or `rejected`.
`executed` means SDK acceptance; physical completion remains `unverified`.
An ACK timeout becomes `unknown`, never assumed success.

Navigation separately matches task state to the original `request_id`
and `generation`. Task activity confirmation is not an actuator execution ACK.
A Chat domain start response with `starting` or `partial` does not yet allow
sending text: the matching domain must report fresh `ready`. Producer errors
remain visible in task cards and details; echo and fallback audio do not
confirm working AI/TTS.

Height and roll balance use advertised position/mode capabilities and global
operator ARM. stop_verified=false does not establish physical cancellation.
Manufacturer figures remain blocked pending interruption characterization.
Values describe last accepted commands, not measured posture.

STOP is always available without a safety envelope. W/S/A/D and arrows work
in Control and Calibration outside editing fields, without key repetition,
with fresh manual permission. Space outside fields sends STOP.
Release, focus loss and a hidden page end hold. For operator/manual/panel this
does not automatically disarm; Pi's watchdog bounds missing renewals.
Other timed sessions retain their revocation rules. Lost connectivity does not
confirm physical stopping. A new page respects [panel ownership](../manual-panel-authority.md);
taking over a different panel_id requires STOP, a fresh generation and explicit ARM.

## Devices and resource use

RAW/PROC/SSD/TRACKER identify frame types. Capture is the process holding the
camera; URL is the source of an existing image. Disabling refresh does not
stop the camera or task. Changing a URL does not acquire the camera. Only
same-origin HTTP paths under `/camera/`, `/vision/` and `/snapshots/` are
accepted. Frame age comes from the frame timestamp. Metadata age and the timestamp
of the frame actually loaded are shown separately; stale displayed images dim.

Reads allow one active request per address, a timeout, bounded backoff and
pause in hidden tabs. Safety polls once per second, catalog and System every
5 seconds, device telemetry every second and ownership every 10 seconds.
Device images are fetched individually on demand or every 2 seconds with
preview enabled; Overview refreshes fresh images from active producers. SSE applies real events
and retains producer timestamps; unavailable SSE leaves periodic reads active.
Zero is a valid reading, `null` remains unknown. Polling never makes an old
measurement fresh.

One executor owns UART and publishes telemetry through BUS. The LCD is
mounted sideways: preserve 270° compensation, boot sequence, SSH and Wi-Fi.

## Administration and resource recovery

System defaults to observation. Explicit administration enables
`start`/`stop`/`restart`. `enable`/`disable` separately changes autostart; the
API prevents enabling autostart for on-demand units. Dependencies, consumers
and refusal reasons remain visible.

Recent logs are read only after clicking the unit's log button. The journal
endpoint accepts units from the common catalog, uses no shell or sudo and
limits reads to 50 lines, 64 KiB and two seconds. Missing permission remains
unknown. CPU, memory, disk, temperature, Git and raw graph data are in details.

First STOP, end the task and normally stop its owner. Forced release is a
separate manual procedure: fresh inventory, exact selected PIDs, typing the
resource name and separate consent. The backend protects base services,
UART and LCD. Recovery is never automatic.


### Passive tracker

S6 selects `face`, `hand` or `none` from the catalog `option_schema`.
Selection sends no request; a separate button starts or ends observation.
S6 starts no motion controller and writes no actuator authorization.
A different mode requested by active Follow Me returns `409` with
`blocked_by`; the operator ends that task before changing the mode.
Ending S6 preserves the tracker and mode required by remaining consumers.
The legacy `/vision/tracking/mode` and its `/api` alias use the same
orchestrator; GET only observes.

### Presentation quality

The API preserves `observed_at`, explicit `stale`/`offline`, errors and
data readiness. A newly published error is not a healthy measurement.
Null or invalid packets expire previous geometry. Quality changes at
the same timestamp redraw the presentation. Older healthy observations
cannot replace newer ones, while explicit source failure expires a healthy
appearance. A fresh FAILED/IDLE task status remains visible regardless of
map readiness. Zero is preserved for battery measurements as well.
Navigation reads the bounded map, pose and path cache through `/state` and
`/api/navigator/status`; reads neither refresh source time nor start producers.

## Verification without the robot

```bash
node --experimental-vm-modules --test tests/operator_panel.test.mjs tests/operator_panel_shared_review.test.mjs tests/legacy_catalog.test.mjs
RIDER_TEST_ISOLATED=1 .venv/bin/python -m pytest --noconftest -q tests/test_operator_event_cursor.py tests/test_operator_navigation_state.py tests/test_operator_service_logs.py
.venv/bin/python tests/operator_fixture_server.py
```

The fixture server binds loopback only and uses stdlib and in-memory data.
It does not import the robot API, SDK, BUS or systemd. It prints its local URL.
Automated tests do not authorize physical movement. Actuator tests require
separate explicit consent from a prepared operator.

The System page enables service controls immediately when fresh API permissions allow the action. No administration switch is required. Disabled actions show their reason, including protected API operations and on demand autostart restrictions.

The overview (/view) RAW camera card has one Camera ON/OFF button. It controls the passive camera preview task through explicit clicks. Opening the page does not start the camera; other camera consumers are shown alongside its state.

Compact ON/OFF buttons beside RAW, PROC, OBST and TRACKER control passive tasks. PROC and OBST share the local obstacle pipeline and switch together; TRACKER selects passive face detection without a movement controller. Tasks reference-count the shared RAW capture and frame feed: stopping one keeps them running for other consumers.
