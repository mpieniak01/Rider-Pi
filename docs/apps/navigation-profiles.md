# Navigation profiles and SLOW v1

Rider-Pi owns the saved driving profile; both panels read the same configuration.
Selections are `legacy`, `cautious`, `balanced` and `fluid`. The three new profiles
are experimental candidates. Selecting one does not qualify physical driving.

## Configuration

GET `/api/navigation/config` adds a presentation-only `behavior_catalog` with
version, support, active identity, read-only definitions and
`effective_policy_sha256`. The digest covers behavior identity and effective
profile parameters; full configuration revision, model and source are checked
independently. The catalog is never persisted as a configuration field.

POST retains the existing CAS contract:

```json
{"revision":0,"values":{"behavior":{"version":1,"profile_id":"balanced","profile_revision":1}}}
```

Missing behavior in an older file means Legacy. No automatic migration selects
a new profile and the browser cannot supply arbitrary policy parameters. Both
repositories must agree on profile revision and digest. Changing a released
definition requires a new revision and qualification.

Saving requires stopped navigation/observation goals and fresh stopped executor
state with zero output/target. The read and atomic save share the executor
settings mutex; STOP bypasses it. Revision conflicts, motion and a busy mutex
return 409. A changed profile writes observation mode and clears verified,
calibration_id, model_sha256 and sweep_verified. It starts/stops neither camera,
models, services nor motion and never restores ARM. Manual correction keeps the
automation paused; explicit resume still needs three fresh positive frames.

## Capability and execution

Decision protocols 1/2/3 keep their numbering. New behavior is independently
negotiated through `temporal_navigation_v1: true` in the authenticated host vision
status. A new profile requires that preflight capability before acquiring motion
authority. Older pairs retain Legacy and reject unknown SLOW.

Venom assesses connected regions, corridor location and distinct fresh capture
history. SLOW requires previously qualified clearance, current near-corridor
support and the exact reduced speed factor from the profile. Pi checks profile/
digest, model, revision, run/frame/sequence, original age and remaining deadline.
It uses the same executor and pulse/permit limits. TTL, ARM windows and operator
speed limits are not increased. Near hazards produce ZERO; expired or latched
runs cannot revive from a later GO.

Calibrated 3D collision and near guards retain their veto, including objects
above the projected floor footprint. Bad captures, source loss, duplicate
captures and tracking loss cannot qualify clearance. Profile/model selection
never restores movement permission.

## Panels and tests

The Pi navigation panel separates saved selection and draft, shows read-only
parameters and distinguishes raw prediction, stabilized assessment, action and
reason. Late responses cannot replace a newer revision. Applying is explicit;
page load, refresh and draft selection never start motion.

A valid SLOW permit is limited permission, not an SDK acknowledgement or actual
motor motion. Image color and model decisions are also separate from authority.
Explicit semantic model selections remain observation-only.

`tests/test_navigation_behavior.py` and
`tests/operator_navigation_profiles.test.mjs` use isolated local state and mock
outputs. The full automatic suite runs in WSL, never on physical hardware.
Observation and physical acceptance remain a separate operator step; profiles
have not yet demonstrated physical continuity or obstacle accuracy.

## Rollback

Stop the loop, select Legacy and inspect a fresh observation. A normal profile
save clears previous driving approval. Before downgrading code to a validator
without behavior, preserve configuration and, while idle/disarmed, remove only
that field and reset mode/verified/calibration_id/model_sha256/sweep_verified to
an unapproved observation policy. Never restore movement approval from a backup.
Model identity migration remains separate.
