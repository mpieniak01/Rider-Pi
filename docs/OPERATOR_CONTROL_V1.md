# Operator priority — contract v1

Continuous journeys use the separate explicit [Automat2 v1 contract](AUTOMAT2_JOURNEY_V1.md); the timed lifecycle below still applies to the ten-second trial.

The extension is explicit: `POST /api/navigation/trial` accepts
`operator_control_version: 1` with a nonblank `panel_id`. Requests omitting both
fields retain their existing lifecycle. Only motion-executor owns actuation.

## Camera and perception lifecycle

Opt-in starts the existing S14 worker once. S15 retains legacy observation;
cold preparation releases S15 before S14, avoiding concurrent producers.
Manual intervention, pause, resume and consent expiry retain that worker and
frame source. Paused workers observe only. Configuration changes, fatal process
failure and explicit camera shutdown use a separate lifecycle.

`POST /api/resource/camera/pipeline`, `action: stop`, first revokes the dependent
session using a confirmed generation-scoped STOP, then stops the managed
producer and releases capture. Replayed old requests and stale revisions do not
stop a newer session. Foreign consumers produce an explicit conflict.
Camera start only enables images; it never grants motion permission.

## Commands and consent

New commands reuse `POST /api/control` and the existing BUS. They require
`source: manual`, `execution_context: panel`, `panel_id`, `request_id`,
`generation`, `seq`, `ts`, `ttl_ms` and current `settings_revision`.

| Command | Result |
| --- | --- |
| `action: move, intervene: true` | Retires the previous autonomous intent, performs a bounded correction using Pi settings, and leaves autonomy paused |
| `action: navigation_pause` | Zeros motion and hands authority to the operator while retaining perception |
| `action: navigation_resume` | Grants autonomy a new generation and begins qualification |
| Global `stop` / `estop` | Existing independent disarm / latched emergency path |

V1 requires explicit navigation consent: `owner: navigation`,
`arming_mode: timed`, `0 < lease_s <= 10`, bound to a panel. Transfers retain
the original deadline. Expiry also stops a manual correction. New consent
requires a deliberate action. Ordinary manual operator-mode ARM remains
unchanged and cannot authorize autonomous resume.

Optional `supersedes_operation_id` on pause or `move+intervene` targets the
current autonomous operation. The same holder can cancel its pending resume
before receiving ACK, using the resume's previous generation. Its sequence must
exceed the accepted manual resume sequence; fast NAV commands in the new
generation do not consume the operator sequence space. Wrong targets, panels,
expired TTL, revoked consent and post-STOP replay cannot use this exception.
Transfer creates a new generation and consumes the target. Local `turn` aliases
use the same protection; the panel sends `move`.

Identical requests with the same `request_id` return the recorded outcome
without actuating again. Changed payloads return `operator_request_conflict`.
The in-memory ledger retains 32 operations and resets on restart; generation
and sequence validation still reject old requests. Replayed ACKs retain their
original generation even after a newer ARM.

## Qualification and status

Resume creates a new `run_id`. Pi locally requires three distinct consecutive
valid frames captured after the new epoch, checking model, revision, protocol,
sequence, age and source context
`camera_session/transport_epoch/pipeline_revision/device_id`.
The host's `clear_count` alone is insufficient. Invalid or repeated evidence
resets the series. Old inference results and STOP callbacks cannot affect a
newer generation. Decision leases, watchdog and freshness checks continue
after qualification.

Safety status adds `operator_control`:
`{version:1,state:idle|paused|qualifying|active,operation_id,generation,reason}`.
`panel_control.holder` remains bound during autonomy. `version:1` advertises
support, not a running worker or permission to move.
`GET /api/navigation/status` adds `operator_control_version:1`,
`qualification_count` and operation identity for the opt-in worker. Consumers
must also check `running`, `stale` and actual Pi authorization.

Automated tests use isolated fakes only. LAN latency, CPU consumption, physical
motion and braking require a separate operator acceptance before release.
ACK alone does not prove physical completion.

Camera OFF rejects active manual motion with camera_pipeline_motion_busy, without
sending STOP. When the manual operator is idle in a paused navigation session,
explicit OFF also ends that navigation consent; camera ON cannot restore it.


## Explicit direction intervention

Safety advertises `operator_intervention_version:1`. This is separate from
legacy timed transfers above. The panel sends one fresh `POST /api/control`
`move` (or normalized `turn`) gesture with:

- `operator_intervention_version:1`, `intervene:true`, `source:manual`,
  `execution_context:panel`, `panel_id` and the ordinary unchanged fresh envelope;
- `operator_consent:true`, a specific `operator_plan`, `owner:manual`,
  `arming_mode:operator` without `lease_s`;
- `device_settings:true`, a direction and current `settings_revision`, retaining
  the saved pulse/hold limits. No arbitrary actuator values are accepted here.

The executor retires the old journey, stops its output, creates a new manual
operator generation and submits only that direction in one serialized operation.
This also works from DISARMED after an automatic failure. Network/sensor/hardware
readiness, settings checks and ESTOP remain enforced. A fresh gesture from a new
panel revokes the previous panel; stale commands cannot borrow that authority.
`ready` describes hardware/sensors, whereas `panel_motion_enabled` describes
existing ARM, so the latter is not a prerequisite for requesting new consent.

During preparation, `supersedes_operation_id` may name the exact original journey
request ID; for active navigation it names the current operator operation. Only
that scope admits an origin generation while fast NAV sequences advance. The
internal journey ARM retains `operator_origin_generation` from preparation, so
an exact panel/mission intervention or cancel can still supersede that operation
if preparation performed a scoped STOP before its new navigation generation.
A different mission, panel or arbitrary stale generation cannot use this path.
Manual status publishes `operator_control.state:paused` and
`operator_control.operation_id` equal to the gesture request ID, without enabling
legacy resume, so status arriving before ACK can identify the panel's own transfer.

Releasing/cancelling before the gesture ACK sends `mode:release` with the same
version/`intervene`, original generation, panel, fresh envelope and
`supersedes_operation_id` equal to the direction request ID. It requires no
consent and grants no authority. The executor stores a bounded cancellation
tombstone before a delayed gesture can act, or zeros the exactly matching manual
operation after it was accepted. `supersedes_navigation_operation_id` additionally
names the original autonomous operation targeted by that gesture. When origin
generation, holder and this target still match active navigation, cancel retires
that old navigation too. In the same DISARMED origin a cancel-only generation
revocation invalidates pending preparations; it cannot grant consent/output.
Duplicates are checked before changing authority or stopping output. An obsolete release or old scoped journey STOP
cannot stop a newer gesture, owner or generation. An authorized ordinary manual
move/turn also supersedes the previous intervention operation within the same
generation; its older origin-scoped cancellation cannot zero that newer goal.
Held-motion renewal is serialized after the initial ACK and uses the existing
current-generation release path. Global STOP/ESTOP retain their
independent priority. HTTP confirmation uses the original `command_generation`
and the new ACK `generation`; it does not establish physical displacement.
