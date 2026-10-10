# Physical motion: software contract and manual characterization

This release implements software safeguards and mock verification. **The robot
has not been driven for this work. Physical characterization is not complete.**
#256 covers code and [calibration tools](calibration.md). Tool review does not
require physical measurements: profile values are local operator configuration,
without a separate PR. An SDK ACK confirms a write, not motion, stability,
distance, stopping time or physical arrival.

## Implemented behavior

| Area | Contract |
| --- | --- |
| Time | Real monotonic dt; invalid/nonfinite/nonpositive/excessive dt stops and disarms |
| Ramp | Bounded normalized command change per second; reversal reaches zero before opposite sign |
| SDK | `rider_move_x(runtime=0)` is held until replaced; repeated accepted output is bounded by the existing goal/lease gate |
| Yaw | Canonical yaw negative=left, positive=right; pose heading is CCW positive |
| Zero goal | A fresh authorized zero MOVE writes zero immediately, retains the current valid lease, and gets a SDK ACK |
| Fault/timeout | Sensor/intent/source loss and goal timeout stop through the same gate and disarm; fresh data never restores consent |
| Sensors | One UART owner, one transaction per pass; finite original per-axis and battery observation times, 2.5 s software age budget |
| Battery | SDK percent 0..100 becomes normalized 0..1; 1% is 0.01; invalid/missing data is null, never a healthy zero |
| Tilt/battery policy | Thresholds and physical reaction remain manual_characterization_required |
| Heavy actions | Height, balance and prebuilt actions remain gated and unavailable where safe interruption is uncharacterized |

Ramp values have command units, not m/s or m/s². Even a tiny nonzero normalized
command may become the minimum nonzero SDK step; it is reported as moving.
Software defaults are inherited bounds, not physical measurements. Small ramp
values cannot promise a small physical acceleration. STOP bypasses ramping but
its mechanical effects remain unverified.

The front ROI detector is a heuristic. Old cached frames retain original capture
age. Missing/failed/unconfirmed-clear input cannot cause motion. Autonomous
exploration and ReturnHome remain passive with `navigation_traversal_unverified`:
neither ROI nor point A* proves a swept corridor and braking horizon. A manually
verified pose/current HOME and range/footprint/traversal records can support a
passive plan only; they do not enable MOVE. No stale task resumes after restart,
source switch, lost consent or data fault. Manual drive uses its explicit lease.

Map and pose must share the exact current `calibration_id` and `reference_id`.
A changed manual reference clears the mapper's prior cells/range and cancels an
existing return path. Old cells expire to UNKNOWN, including operator statistics;
a matching request ID alone cannot validate a map from another coordinate frame.
Explicit failed/offline/stale camera metadata remains failed through ROI/history.
An invalid stream frame cannot create a fresh processed-file fallback.

The operator view reads an existing internal point plan and its confirmed HOME.
`plan_observed_at` is the older original map/pose time; a process heartbeat never
refreshes those points. A changed reference/HOME, failed pose or explicit STOP
clears the cached plan. Map, pose and plan overlays require the same frame/HOME.
The catalog requires exact `data_ready: true` and `navigation_ready: true` from
the matching current navigation producer; a running process alone is not ready.

There is **no separate DISARMED planning request route** in this release. Retained
legacy start/ReturnHome routes require an original motion-consent envelope, and
the controller remains passive. The panel therefore disables both requests and
shows `passive_plan_request_unavailable` / `navigation_traversal_unverified`.
Do not arm the robot to obtain a plan. Planning availability is a future explicit,
non-actuating API change; displaying a previously published plan is available now.

## Preparation for a future manual attempt

### Deployment limits

Both ordinary `pi-preview` and `pi-release` protect changes to `drivers/` and
`systemd/`. This migration therefore needs a separately reviewed, one-time
controlled Git and unit cutover. `systemd_reconcile.py` only links unit files and
reloads systemd; it does not transfer UART ownership or atomically switch code
and unit definitions. Fresh inventory of installed unit paths, interpreters and
drop-ins is required before planning the handoff. Deployment remains pending;
no device cutover was performed for this software verification.

For a planned rollback, restore the unit manifest with the **new**
`scripts/systemd_reconcile.py --rollback <manifest-backup-directory>` helper
before restoring the old Git revision, then reload systemd after the Git restore.
Do not automatically restart legacy SDK consumers: the old constructor may
actuate hardware. Preserve Wi-Fi/SSH, sideways LCD compensation 270, boot and
manual Jupyter; leave `--consolidate-boot` off. These limits require an explicit
operator-reviewed rollout, not an automatic deployment or movement test.

1. Operator chooses one concrete maneuver and writes its plan: floor, clear space,
   measured boundaries, load, battery, cable clearance, observer and reachable
   STOP/E-Stop. The development robot is attached to power by cable; provide slack
   and clearance. Approval for camera/deployment/service start is not movement approval.
2. Confirm current firmware and sole UART owner, fresh telemetry, DISARMED,
   capabilities and emergency stop availability. Unknown/failed state means no attempt.
   Do not clear an E-Stop automatically or enable an unverified actuator.
3. Agree on the exact command and the one attempt's maximum time. An operator must
   approve each attempt separately. No loop, unattended calibration, CI/E2E/pytest
   or diagnostic command may send these maneuvers.
4. Use the existing interactive `scripts/manual_motion-probe.py` for one bounded
   attempt only after approval. It requires a TTY, plan and token confirmation,
   limits the command duration to 0.01..0.25 s and sends STOP in cleanup. It refuses
   uncharacterized capabilities. A longer observation requires a separately
   reviewed operator plan; do not bypass the gate to obtain it.
5. Observe actual response and STOP with an independent measurement/time reference.
   Stop immediately on uncertain space, cable tension, delayed stop or instability.
   Record refusal, timeout, firmware output and outcome as well as successful data.

These are instructions for a prepared operator, not authorization to execute them.

## Measurement record and acceptance still open

Use `config/odometry-calibration.example.json`; it contains no invented values.
Record raw observations and repeatability with firmware, floor, load, battery,
cable state, operator, date and commit. Exact signed step tables are used without
interpolation; conditions define where the record may be applied.

- [ ] Verify sign and units of SDK/IMU yaw using independent orientation measurement.
- [ ] Measure smallest effective forward/backward/left/right steps.
- [ ] Measure acceleration and deceleration for each accepted command ramp.
- [ ] Observe reversal through zero and mechanical settling; no unapproved sweep.
- [ ] Measure command-to-stop delay and stopping distance on the recorded surface.
- [ ] Characterize height/balance/actions and interruption before enabling capabilities.
- [ ] Characterize battery validity/range, low-charge behavior and safe reaction.
- [ ] Characterize IMU tilt, offsets/noise and the approved response to unsafe posture.
- [ ] Measure position/heading error, footprint clearance and range/traversal coverage.
- [ ] Verify swept-corridor margins and stopping horizon; review the planner/guard before autonomous actuation.
- [ ] Choose approved physical thresholds/reaction and record their applicability.
- [ ] Manually confirm selected parameters under those conditions and review rollback.

No checkbox above is completed by mock tests or vendor protocol inspection.
Loading a file alone does not establish a current robot reference: the separate
[operator reference API](odometry.md) stays non-actuating and requires DISARMED.

## Lightweight verification already available

Tests use fake SDK/clock/BUS/files: ramp/dt/reversal, immediate zero versus fault,
sensor missing/stale/future/order, actual output age, frame cache metadata,
uncalibrated model, reference replay/restart/API errors, stale map/pose/range,
bounded allocation, UNKNOWN routes and yaw sign. Run these in the existing Rider
WSL venv with isolation. No packages/daemon/second gate were added. API/domain
status writes are bounded and live in `/run/rider-motion`.

LCD remains physically mounted sideways with compensation 270; boot, splash,
Wi-Fi/SSH and manual Jupyter policy remain the reference configuration.
