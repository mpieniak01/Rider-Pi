# Calibration: profiles, measurements and reference

The /calibration page uses existing JavaScript modules and Flask.
It installs no packages or models. Opening the page reads state;
it starts no services and sends no ARM, STOP or motion trial.

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
