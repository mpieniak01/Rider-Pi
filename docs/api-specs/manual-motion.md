# Manual control: device settings and operator intent

Rider-Pi owns calibration and named motion profiles. Clients read
`GET /api/calibration/controls` through the negotiated `rider.calibration`
v1 envelope; its data is `rider.manual_settings` v2. POST uses the same URL.
PC and Venom do not maintain another authoritative settings copy.

## Parameter descriptions

`parameter_schema.version=1` adds `direction_fields`, `value_fields`,
`actuator_fields`, `ramp_modes` and constraints. Numeric fields describe type,
unit, display unit/factor, bounds, precision and meaning. Slider step has
`exclusive_minimum=true`. Display value = API value × display factor; divide
by that factor exactly once when saving. Commands use normalized magnitude
0–1, seconds and normalized magnitude/second. A percentage is neither m/s nor
a percentage of the current profile maximum.

Schema bounds describe technical support; `directions` contains the operator's
calibrated minimum/maximum. Zero always means no motion. The current panel
duration range is 0.01–1.0 s; the initial pulse is 0.25 s. Read live descriptors
rather than hardcoding either. Pi validates constraints; clients never execute
a textual rule. Unknown schema versions do not grant motion permission.

## Movement intent

`control_modes.version=1` advertises supported modes, directions, endpoint,
renewal/timeout timing and stop semantics. A command uses `action=move`,
`direction=forward|backward|left|right`, `mode=pulse|hold|release`,
`device_settings=true` and `settings_revision`. Existing source=manual,
execution_context=panel, generation, seq, request_id, ts and ttl_ms remain
required. Include the bound `panel_id` when panel ownership is advertised.
Do not also send vx/yaw/duration with device settings.

- Missing mode means pulse. Pi resolves magnitude and duration from calibration.
- Hold renews every 150 ms. Missing renewal for 500 ms stops movement while
  preserving operator ARM; this timeout is independent of pulse duration.
- Release ramps to zero and keeps ARM, with a hard zero no later than 500 ms.
- STOP stops immediately, disarms and invalidates the generation.
- Hold/release belong only to the operator/manual/panel session.

The latest valid sequence replaces the goal; commands never form a replay
queue. Reversals pass through zero and the configured pause. The browser keeps
one request in flight and the latest pending intent, checking gesture, revision
and generation again before dispatch. STOP invalidates pending negotiation too.
Release, pointer cancellation, capture/focus loss and a hidden page end a hold;
Pi's watchdog bounds browser/network loss.

## Gestures and confirmations

A click shorter than 180 ms sends one pulse. A longer press enters hold and
releasing sends release. Mouse, touch, arrows and WASD share the same flow on
Control and Calibration; editing fields retain their normal keyboard input.
A new direction replaces the previous one; releasing an old key cannot cancel
a newer intent.

Envelope version, contract version, descriptor version and settings revision
are separate. Executor state reports the applied `manual_settings.revision`,
`intent_mode`, target and output. Settings may be saved only while stationary,
including an armed but idle robot. SDK acceptance does not prove physical motion.

[Calibration](../apps/calibration.md) · [Panel ownership](../manual-panel-authority.md) ·
[Command curves](../motion-curves.md). Software tests use fake executors;
physical trials require separate operator authorization.
