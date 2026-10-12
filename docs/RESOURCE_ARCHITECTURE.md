# Shared robot resources and goals

## Ownership and entry points

The panel, HTTP API, CLI and Makefile aliases use `common/service_catalog.py`
and the same execution code. The HTTP process owns one `FeatureManager`.
CLI normally sends commands to that instance.

Emergency `--direct` dispatches the **same handlers and contracts** locally,
without a web server, subscribers or another daemon. Use it on the Pi while
the API is stopped. Do not run independent control modes concurrently.
The shared journal restores verified passive ownership when the API returns.
Direct mode preserves resource checks and motion permission requirements.

| Responsibility | Source |
| --- | --- |
| Goals, aliases, units and dependencies | `common/service_catalog.py` |
| Start/stop, shared consumers and rollback | `services/core/features.py` |
| Systemd execution | `scripts/service-systemd-backend.sh` |
| Closable camera owner | `apps/camera/utils.py` |
| Camera intent/process/frame projection | `services/core/camera_state.py` |
| LCD board configuration | `drivers/lcd/board.py` |
| LCD ownership, presentation and SPI release | `apps/ui/lcd_sink.py` |
| Guarded LCD power-off | `apps/ui/lcd_power.py` |
| Face animation and emotion events | `services/api_core/face_anim.py` |
| Sysfs ACT/PWR LEDs | `drivers/led.py` |
| UART, actuators and telemetry | Existing motion executor |

Private backends implement controller decisions; they are not alternative
public goal managers. Boot uses the shared LCD backend before HTTP is ready.
Manual `dev_*` hardware diagnostics are separate from ordinary goal startup.

## One button for a goal

Select a goal and its variant in Tasks and control. One button starts its
required package or ends the goal. End releases only managed units with no
remaining consumers; base services remain available. System administration
retains access to atomic units.

Global arming remains the operator's separate decision. Passive goals, camera,
face and reads do not arm the robot. Tests that can move hardware still need
separate consent.

The journal records Linux boot ID, unit PID and start timestamp. After an API
restart, only passive goals with matching process identities are restored.
Motion intent and arming are never restored. Mismatched ownership is external;
goal STOP does not falsely confirm that external processes stopped. Use an
explicit service alias to stop a known external unit.

## CLI

Use the existing runtime interpreter from the repository directory:

```bash
python3 scripts/robot_ctl.py status
python3 scripts/robot_ctl.py start s2_camera_preview
python3 scripts/robot_ctl.py stop s2_camera_preview
python3 scripts/robot_ctl.py start s2_camera_preview --seconds 30
python3 scripts/resource_ctl.py lcd off
python3 scripts/resource_ctl.py service status camera-capture@raw.service
python3 scripts/resource_ctl.py service stop camera-capture@raw.service --direct
python3 scripts/robot_ctl.py stop s2_camera_preview --direct
python3 scripts/sys_led-control.py off --direct
make preview-on
make lcd-off CONTROL_MODE=--direct
```

`RIDER_API_URL` / `--url` selects the HTTP host; local `--direct` rejects
`--url`. Moving CLI starts require a TTY and the original operator envelope
in `--control-file`, without regenerated timestamps, TTL or permission.
Timed sessions are new passive sessions only.

Legacy service/LCD/camera/vision scripts delegate to these clients. Names
containing kill/hard/reset do not perform broad process kills, GPIO guesses
or board resets. LCD reset/hard aliases use shared on/off operations.

## Resource lifecycle and idle energy

For this CM4 board, physical LCD compensation is 270°, BCM BL=0, RST=27,
DC=25. `FACE_LCD_*` settings have one source. Camera `PREVIEW_ROT` does not
alter LCD mounting. `RIDER_LCD_OWNER_LOCK` defaults to
`/tmp/rider-lcd-owner.lock`; the file lease excludes another shared renderer.
Descriptor inventory also detects vendor processes outside that lease.

RAW/EDGE/SSD share a closable camera handle. Reinitialization closes the old
backend; stop/failure executes Picamera2 stop+close or V4L2 release.
Capture defaults to headless; explicit `DISABLE_LCD=0` enables the common
display sink. `NO_DRAW=1` does not initialize LCD. Headless camera stop does
not change LCD power.

Face runs on demand. Studio, `/face/play` and legacy LCD render share one
runtime. Existing mood/listening/waiting/gesture/audio events are the future
chat integration point. No GPT client or extra process is added. Battery FPS
and idle expiry remain bounded; cable mode is an explicit setting.
Direct CLI play stays in the foreground for 1–300 seconds with final cleanup.

Sysfs ACT/PWR LEDs, LCD backlight and MCU RGB are distinct devices. LED status
reads the bracketed active Linux trigger; blinking uses the kernel timer.
CLI blink cleans up on Ctrl+C/SIGTERM only if its session generation remains
current. Generations are shared in `RIDER_LED_STATE_PATH`, default
`/run/rider-motion/led_state.json`.

UART capture remains opt-in; see [UART sniffer](uart-sniffer.md).
Missing fresh frames never proves camera power-off. Accepted GPIO/SPI writes
do not measure power consumption or prove physical display visibility.

## Delivery and checks

Deploy the complete increment including private backends. Existing noninteractive
privilege and journal write access are required. Restricted sudoers must include
the new controlled `service-systemd-backend.sh` path, without allowing arbitrary
commands. Do not perform broad systemd synchronization during this update.

Before publication run full WSL regression, then verify the Pi preview: camera
lifecycle, existing startup screen, orientation and idle-off. Movement tests
remain separate. Fake hardware checks cannot establish physical behavior.

## Previewing this scope

```bash
python3 scripts/dev_pi-deploy.py preview --resource-scope --restart-api
```

The flag allows only a fixed list of LCD/LED backends and aliases. Capture
must be inactive. The tool closes old API/LCD processes before checkout,
restores the previously active display and records this lifecycle for rollback.
The flag does not restart the motion executor.
