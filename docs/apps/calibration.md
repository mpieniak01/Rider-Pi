# Calibration: device settings and manual trials

The /calibration and /control pages use the same settings stored on Rider-Pi.
Opening either page only reads state. It does not start services or arm the robot.

## Operator workflow

1. Prepare the robot, space and cable. Arm once with the global button.
2. Set direction magnitude and duration. Calibration additionally exposes minimum,
   maximum and slider step per direction, acceleration/deceleration for each axis,
   and reversal pause.
3. Save between pulses. Saving is allowed in ARMED and DISARMED when the executor
   reports zero target/output, no active deadline and no motion. It preserves
   arming and the session generation. A save never sends a movement command.
4. Click an arrow, observe the physical result, adjust and save again. Unsaved
   drafts disable new pulses until confirmed. Normal pulse expiry stops the
   drive while keeping operator arming; STOP disarms and invalidates queued commands.
5. Both screens poll the same settings. An intervening revision change requires
   reviewing values and another click; a conflicting save is never retried automatically.

The sliders tune commands, not measured speed. “Too fast/too slow” is operator
feedback, not proof of metric odometry. Minimum is an operator supplied usable
target threshold; it is not a lower bound on every intermediate ramp output.

## Authoritative settings contract

GET /api/calibration/controls returns rider.manual_settings version 2 inside
the existing version 1 HTTP envelope. The schema contains:

| Field | Meaning |
| --- | --- |
| schema_version | Stored shape, currently 2. |
| revision | Persistent integer for concurrent updates and motion admission. |
| directions.forward/backward/left/right | minimum, maximum, step, speed, duration. |
| values.speed_limit | Global normalized ceiling within deployment limits. |
| values.linear_rate/turn_rate | Command acceleration per second. |
| values.linear_deceleration/turn_deceleration | Command deceleration per second. |
| values.reversal_pause | Pause at zero during reversal, seconds. |

Normalized magnitudes are 0–1, bounded by the configured global ceiling (default
0.6). Duration is 0.01–0.25 seconds including ramp up and down. Short pulses may
not attain their requested magnitude. The panel displays a software estimate
of the reachable command peak; it is not a physical speed prediction.
Impossible direction minima are rejected. Zero remains a stop.

POST uses {revision, values, directions}; directions and their fields may be
partial. The server validates an atomic update against fresh idle executor
status and the expected revision. Conflict or non-idle status returns 409.
Invalid values return 400; unavailable storage returns 503.
No command is issued by this endpoint.

Panel arrows send device_settings=true, direction and settings_revision in the
existing safety envelope. Pi resolves the magnitude and duration, then its single
executor applies smoothing and writes through the UART adapter. Other protected
motion producers must also include the current revision. Old revisions are rejected.

Compatibility values linear_speed and turn_speed mirror forward.speed and
right.speed; pulse_duration mirrors the largest directional duration.
They do not define independent runtime settings. Legacy writes explicitly affect
both directions of their axis; new clients should use directions.

## Persistence and migration

Default location: ~/.local/state/rider/motion/settings.json outside the checkout.
RIDER_MANUAL_SETTINGS_PATH overrides it for isolated environments. Files are
atomically replaced with permissions 0600. Existing manual settings are migrated
once, preserving previously effective capped values. Only when no manual store
exists may a legacy active profile seed the initial settings. Corrupt existing
stores never silently fall back to defaults.

Archived profile/measurement/odometry APIs remain available. Activating an archive
does not overwrite motion settings or create motion consent. These records are
evidence for odometry; they are no longer the panel's motion configuration form.
Unverified autonomy remains blocked.

## Hardware interpretation and safety

Rider SDK commands describe UART goals; they expose no motor current/voltage
control. Magnitudes and ramp rates are not m/s or physical acceleration.
Height uses the Rider interface's native 75–115 range. Rider figure codes are
1 sway, 2 vertical, 5 lift_rotate, 6 circular (255 reset). Posture and figures
remain unavailable where safe cancellation has not been verified.
Do not infer encoder feedback from read_motor, or repair implausible raw yaw
with modulo. Raw observations retain original timestamps in diagnostics.

Panel arming and physical test consent are separate. Automatic pytest/CI uses
fake adapters and isolated files; it cannot gain hardware access from panel consent.
Physical trials require a prepared operator and separate explicit authorization.

## Simple named motion profiles

Profiles live in the same device settings file (up to 16), each holding every
direction and smoothing value. Select a profile then Apply selected; this is an
atomic idle settings change and never arms or starts motion. Save as new stores
current settings and any visible draft under the entered name. Update selected
replaces that preset and can change its name. Delete selected removes the preset
while retaining current settings. Normal Save settings changes current settings
only; a modified active preset is explicitly marked. Pending drafts must be saved
before applying another profile or deleting. Revision conflicts require review,
never automatic retry. Both screens show the active profile; full management is
on Calibration. Names such as Desk or Floor describe operator use, without preset
speed assumptions or a claim of surface safety. Profiles cannot raise deployment
limits or enable unverified actuators/autonomy.

## Posture controls

Control and Calibration share one posture component. Height (75–115) sends on slider release; roll balance has an explicit Apply button. Both use the global operator arming gate, current settings revision and the same executor state. Reported values are last accepted commands, not measured actuator positions. Polling preserves an edited selection. Height and balance are position/mode settings; stop_verified remains false and does not claim cancellation. Manufacturer figures remain blocked until interruption is characterized. Automated motion tests remain independently disabled.
