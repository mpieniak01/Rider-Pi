# Automat2 — journey contract v1

A journey is a separate explicit opt-in for Venom. `POST /api/navigation/trial`
retains its ten-second consent and existing operator lifecycle. A journey never
renews trials or repeatedly arms the executor.

## Admission

`POST /api/navigation/journey` accepts the trial envelope: `request_id`,
`generation`, `ts`, `ttl_ms` (at most 500 ms), `config_revision`,
`settings_revision`, `operator_consent:true`, `operator_plan`, `source:manual`,
`execution_context:panel`. It additionally requires `journey_version:1`,
`operator_control_version:1` and a nonempty `panel_id`. Request IDs contain no
whitespace.

Fresh executor state and Venom must advertise `navigation_journey_version:1`.
The policy must admit drive and use accepted avoidance v3 (`enabled:true`,
`protocol_version:3`, `sweep_verified:true`) with current model/zone acceptance.
Both `image` and `ground` geometry remain available. Ground requires real
`fx`, `fy`, `radius_ratio` and current acceptance; missing calibration is never
filled automatically. Existing avoidance limits remain at most 0.1 SDK and
150 ms per pulse.

Admission reuses the trial preparation transaction. Cold preparation reserves
camera, releases the previous producer, configures drive, obtains one consent,
starts a worker and confirms its exact operation. A compatible warm S14 producer
instead retains capture, transport and model demand. Reuse requires fresh
`warm_navigation_version:1`, `warm_ready:true`, matching policy revision and
native camera session/transport epoch/pipeline revision confirmed by the host.
Missing or incompatible readiness takes the cold path. `preparation.warm_reused`
and separate phase timings report which path actually ran.

STOP or a newer generation cancels preparation. Replaying a request ID never
starts another mission. Preparation progress adds `journey_version:1`.

## Consent and feedback

Internal ARM uses `arming_mode:journey`, `owner:navigation`, `journey_version:1`,
`journey_id` equal to the journey request ID, `operator_control_version:1` and
`panel_id`, without `lease_s`. Only an explicit panel request may grant it.
Bootstrap has a five-second watchdog. Thereafter accepted NAV goals, including
ZERO, renew only the short independent feedback watchdog.

Every goal carries the mission identity, matching generation/operation/sequence,
a short TTL and both Pi-local decision and feedback deadlines (at most 500 ms).
Validation alone cannot renew consent: the controller must accept the goal.
Each motor pulse ends at its own deadline. Waiting for the next fresh decision
holds ZERO; lost feedback ends consent. GET, Refresh, preview, reconnect and
replayed ARM never renew a journey.

## Frames and maneuver progress

Frame metadata and the Venom reply contain exactly
`journey:{version:1,id:<mission id>,maneuver_epoch:<integer>}`. The initial epoch
is zero. The host adds a process nonce, `host_session`; a changed nonce terminates
the running mission. Trial and observation frames omit journey metadata.

Avoidance retains existing v3 evidence: a clear side and guarded steering path,
current model/zone, consecutive confirmations and a bounded correction budget.
Captures before/during a correction or its settling interval cannot authorize
the next maneuver. Only Pi increases the epoch, by one, and resets its correction
budget after three accepted fresh GO replies whose frames were captured after
the last correction and settling. GO without a preceding correction never resets
the budget. Obstacles/uncertainty break this confirmation series. A brief wait
for fresh feedback preserves the series while keeping motor output at ZERO.

Venom admits epoch +1 only after its own confirmed clear path following a
correction. A jump, rollback, foreign identity or missing exact echo terminates
the mission. Unsuccessful steering ends with STOP; time never resets its budget.

## Termination and status

STOP, ESTOP, lost decisions, configuration changes and manual intervention end
the journey. `navigation_resume` cannot revive it. Manual correction requires
new explicit manual consent; journey authority never becomes an unbounded manual
ARM. A versioned [direction gesture](OPERATOR_CONTROL_V1.md#explicit-direction-intervention)
carries this new manual consent in the same executor transaction; a separate
button/ARM round trip is not required. ESTOP is never cleared by it.

A healthy S14 producer remains observation-only after terminal mission STOP,
manual takeover or transport failure. Its latest mission outcome is archived
before observation replaces the live row. A new explicit Start must persist a
new matching service intent, generation and journey ID. The retained process
creates a new run ID, empty decision lease and three-frame qualification after
that boundary. Old GO, ACK, intent, ARM or callback cannot revive the old mission.
Configuration/source changes and explicit camera OFF remain cold lifecycle
boundaries. Process restart cannot restore a mission.

Main capture and watchdog serialize lifecycle transitions and status publication
under one reentrant mutex. Authority is sampled inside this transaction, so a
queued old sample cannot retire a newly bound mission. The lifecycle never waits
for a decision-lease mutex while holding its own: callbacks may enter lifecycle
while holding a lease lock. Identity failures halt their captured lease only
after releasing the lifecycle mutex. Terminal STOP callbacks retain the original
run/generation scope; old replies are omitted from a newer epoch status.

`GET /api/navigation/status` exposes
`journey:{version:1,id,active,state,reason,elapsed_s,maneuver_epoch}`. States are
`qualifying`, `forward`, `steer_left`, `steer_right`, `waiting`, `blocked`,
`stopped`, `failed`. A completed result remains in status and the latest-run
archive. Safety separately publishes the same journey ID and active consent flag
with short `lease_remaining_s`; the runner owns maneuver progress.

This is reactive camera navigation, without SLAM, odometry, a destination
completion guarantee or monocular centimeter measurements. Automated tests use
in-memory doubles only. Physical acceptance for successive obstacles, pose
changes, transport loss and STOP is a separate operator procedure after preparing
the space and cable. An ACK does not prove traveled distance.

## Decision transport and preview recovery

The runner keeps one HTTP connection to its selected Venom across captures, for
both JPEG and native reference requests. Each POST is sent once. Connection
failure closes the socket; observation retries a new capture, never a replayed
command. Two seconds of inactivity and runner shutdown close the connection.
Redirects and origin changes are rejected. Replies remain bounded to 16 KiB.
`decision_transport` exposes only `connections` and `requests`, without addresses
or credentials.

This transport optimization changes no consent: original capture/feedback
deadlines, maximum speed and pulse duration stay unchanged. Acceptance of a real
camera observation does not replace the operator's physical journey test.
