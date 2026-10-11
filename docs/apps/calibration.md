# Calibration: profiles, measurements and reference

The /calibration page uses existing JavaScript modules and Flask.
It installs no packages or models. Opening the page reads state;
it starts no services and sends no ARM, STOP or motion trial.

## Actual executor observations

The panel shows signed linear_step/turn_step only from motion.sdk_output:
accepted, motion-executor source, original observed_at, exact instance_id and
generation must match fresh executor status. SDK writes have a 0.25 s budget.
Older matching steps are marked history/stale without claiming current motion;
rejected or mismatched data stays unknown. Panel targets and form values
never determine SDK steps.

Roll, pitch and yaw retain raw SDK values without assuming unverified units.
Battery converts only a finite 0–1 fraction to %, preserving real zero.
Each channel has its own observed_at, ready, error and age with a 2.5 s budget.
Fresh status publication never renews observations; a larger producer-reported
age is also respected. One channel's failure neither confirms nor invalidates
others, while a stale parent or hardware/UART failure expires all channels.
The three current motion.dynamics parameters are shown separately from ENV
ceilings, including during hardware failure when software configuration is valid and fresh. Hardware errors are shown separately. Physical_completion remains unverified.

## Profile and units

| Field | Meaning |
| --- | --- |
| motion.speed_limit | Executor limit 0–1 in normalized units, not m/s. |
| motion.linear_rate / turn_rate | Normalized ramp units/s, not measured physical acceleration. |
| odometry.linear_m_s / turn_rad_s | Own measured rates for signed SDK steps: linear ±1…12, turn ±20…70. |
| odometry.conditions | Firmware, surface, load, battery, cable, operator, date and commit. Extra fields are preserved. |
| odometry.observations | Evidence/notes: minimum steps, acceleration, deceleration, reversal, stopping distance/delay, position/heading error, battery and tilt. |
| measurements | Raw successful and failed observations, duration, distance/angle, phase, step and evidence. |

Runtime applies three motion parameters, odometry tables and IMU sign.
Observations, including battery_policy and tilt_policy, record operator notes;
they are not enforced thresholds or guards and do not unlock autonomy.
This change does not migrate SDK scales or existing ENV units.

The form starts with an unverified draft. Initial 0.6/1/2 values are software
settings, not measurements; reported current dynamics can replace them.
Activation respects ENV ceilings captured at executor startup. The watchdog
is not editable. Blank observations remain unknown without physical defaults.

## Operator workflow

1. Enter a profile, conditions and evidence. Saving creates an immutable SHA-256
   revision; it neither activates configuration nor moves the robot.
2. Prepare space and the power cable for physical trials. Explicitly grant
   ARM using the collapsible form, a specific plan and a short lease.
3. Each single pulse requires its own plan and checkbox. Consent resets
   before sending, including on errors. Duration is 0.01–0.25 s; there are
   no sequences, retries or automatic ARM. Watch the robot and use the
   always available STOP. SDK ACK does not prove physical stopping or measurements.
4. Record your own observations, including failures. Whole-trial distance/time
   averages include the ramp and never automatically populate steady-rate tables.
   Read signed SDK steps from executor output, not a slider.
5. After actual measurements, choose manual provenance and explicitly confirm
   your own evidence. Both tables, IMU sign, identifier, operator/date, evidence
   notes and a matching measurement_id record with notes are required.
   Editing the data resets consent.
6. Activate the saved revision in fresh DISARMED with separate configuration
   consent and plan. This grants no motion permission. An unavailable odometry
   model does not block configuration when both consumers are live and motion
   confirms zero target/output.
7. Activation rotates generation and clears the old reference/HOME without SDK STOP.
   Separately use STOP, physically check stopping and position, then enter measured
   x/y/theta and optional HOME in the same frame. The reference form sends neither
   ARM nor STOP; HOME is never assumed to be (0,0).

Automated tests never execute physical trials. LCD mounting orientation
and the startup sequence stay unchanged.

## Confirmation and history

HTTP 202 / pending means submission. GET confirms activation only with the
same hash in both fresh consumers, matching motion instance, applied_ack,
request/seq and command_generation/applied_generation. An unrelated latest
rejection in last_ack does not replace the accepted configuration applied_ack.
After restart, fresh matching hashes from saved_profile give
confirmation=loaded_from_saved without inventing a new ACK.

Activation first persists a local pointer with activation_state=pending.
The executor rechecks DISARMED, no goal/motion, generation and TTL; only after
logical configuration acceptance and generation rotation does it persist
activation_state=applied. A pending entry is not an active profile: the API
shows partial/active_profile_pending, and restart blocks ARM and the odometry
model. E-Stop before logical acceptance or final persistence failure leaves
this entry for repair through a new explicit request. There is no automatic
rollback or acceptance at restart. Older unmarked pointers are also rejected.
E-Stop after logical acceptance is a separate latched safety state; a successful
final write confirms configuration alone and does not clear E-Stop.

Applied describes configuration. Verified measurement record (record_verified),
current model_ready and physical_completion=unverified remain separate.
Missing, stale, rejected or single-consumer confirmation stays unknown/partial.
Mutations are never automatically retried or restamped. References require
matching terminal ACK and observed reference_id/HOME, not HTTP success alone.
Rejection or 8 s without matching confirmation releases the form for a new
explicit request; it never retries. References with an active profile require
the exact profile_digest and a matching transaction in both consumers.

History loads initially, after saving or via “Refresh history”; 2 s polling
only reads runtime. Export uses a saved revision. UTF-8 JSON imports are
limited to 65536 bytes and always become historical with manual_verified=false,
even when the file claims verification. Rollback explicitly activates an
earlier digest with the same guards. Catalogs retain up to 64 revisions;
profiles hold up to 128 raw trial records.

## API and local files

| Endpoint | Operation |
| --- | --- |
| GET /api/calibration/state | Both consumers, active/requested hash, confirmation, model/errors; read only. |
| GET /api/calibration/profiles | Saved revision metadata. |
| POST /api/calibration/profiles | {profile, imported?:bool}; returns digest, profile, created, actuation:false. |
| GET /api/calibration/profiles/<digest> | Selected revision for editing/export. |
| POST /api/calibration/activate | Explicit configuration intent; HTTP 202 remains pending. |
| GET /api/odometry/state | Current reference, model and last ACK. |
| POST /api/odometry/reference | Explicit reference and optional HOME without actuation. |

Activation/reference retain the envelope: generation, increasing seq, source=manual,
request_id, ts, ttl_ms<=500, operator_consent=true and nonblank operator_plan.
Activation always includes profile_digest; references include it when a profile
is active. Existing configuration without a profile retains its contract.
SafetyPanel synchronizes server time; RTT above 500 ms or missing fresh state
blocks mutations. Configuration, reference, ARM and individual trials have
separate consent.

The default config/local/motion-calibration/ directory is ignored by Git.
RIDER_CALIBRATION_DIR may point to another absolute local directory.
Do not publish physical results, profiles, exports or measurements in PRs/GitHub.
These tools and contracts complete calibration issue #256; operators collect
actual physical parameters locally without an additional PR.

See [odometry](odometry.md), [physical motion](physical-motion.md)
and [robot operation](safety.md).


## Manual control and response tuning

The main calibration view provides the camera, direction arrows, STOP, travel/turn
speed sliders and response ramps. Click duration is an advanced setting.
Speed sliders select the next manual trial; ramps apply only after saving and
explicit activation. Manual control uses the single global arm/disarm button;
there is no additional per-arrow consent. Reading, sliders, save, apply and rollback never start movement.
There are no automatic repeats or calibration sequences.

The optional profile object interaction contains linear_speed, turn_speed (0–1)
and pulse_duration (0.01–0.25 s). Both clients read shared Pi settings from
motion.calibration.interaction. They do not grant motion authority.
Legacy profiles remain readable. Existing motion ramps and executor ceilings
stay authoritative. Application still needs both consumer confirmations;
manual response tuning does not require measured odometry or HOME.

Mapping rider-1.4.2-levels-v2 reports signed linear_step command levels in
−127..127, converted to native SDK input by level * 1.5 / 127.
Signed turn_step is −70..70 and corresponds to native SDK turn input.
motion.output.units is command_levels; mapping_id, linear_sdk_value and
turn_sdk_value describe commands, never measured velocity or wheel encoders.
The guarded write hook rounds around protocol neutral 128, including STOP;
the installed vendor library is not modified. Pulse duration bounds time;
command magnitude bounds requested speed.
Measured odometry requires matching conditions.command_mapping.
Old measurements remain inspectable but cannot verify the changed mapping.
Coefficients are never converted automatically.

Measurement tables, pose/HOME, import and detailed observations are advanced
facilities. Operator judgement tunes manual control without verifying metric
odometry or enabling autonomy.

## Global panel arming and separate test permission

The single button on the right displays the confirmed executor state:
red "Robot disarmed", green "Robot armed". Clicking red grants manual panel
permission; clicking green sends STOP. Clearing software ESTOP and ARM follow
one explicit click, sequentially, only after a fresh DISARMED confirmation.
External ESTOP, unavailable hardware, an unconfirmed clock or a missing
confirmation still block ARM. Arming does not move the robot. The panel uses arming_mode=operator: permission remains until operator STOP
or disarming, without a timer or automatic renewal. Changing views does not send STOP.

The safety contract adds execution_context (panel/test), panel_motion_enabled
and test_motion_enabled. The panel sends execution_context=panel. Panel consent
cannot authorize test commands, even with test_operator_consent=true.
A manual physical probe uses its own execution_context=test session and explicit
test_operator_consent=true at ARM and every motion attempt. A test session cannot
authorize panel controls. A single executor session prevents simultaneous control.
STOP invalidates both flags.

Automated pytest/CI remains isolated: real SDK, hardware devices, SSH and robot
network access are blocked independently of either flag. Test consent does not
disable isolation. manual_motion-probe.py requires a present operator, an
interactive terminal and a one-time typed approval; it sends STOP after the probe.

Panel: arming_mode=operator, lease_remaining_s=null. View and focus changes do not disarm. Physical test sessions remain timed with separate consent. Hardware faults and external ESTOP still stop the executor; stale data blocks new commands.

A bounded panel movement pulse stops the drive when it ends, while operator arming remains active for the next click. STOP/disarm revokes the session; test sessions keep their timeout behavior.
