# Operator tasks, services and resources

## One catalog and contract 2

`common/service_catalog.py` owns S0–S11 tasks, units, aliases, capabilities,
resources and shell allowlists. Import and GET requests neither start processes
nor open BUS/UART. No new daemon or dependency is introduced.

| Read endpoint | Contents |
| --- | --- |
| `/api/logic/catalog` | Units, tasks, capabilities and resource consumers |
| `/api/logic/features` | Observed members, requested/state/ready and task options |
| `/api/logic/summary` | Same states and counts, retaining the `summary` envelope |
| `/api/logic/state` | Diagnostic snapshot, never a source of motion consent |
| `/svc`, `/svc/<alias>` | Units: installed/load/active/sub/enabled/PID |
| `/api/services/graph` | Same catalog and shared systemd observation |
| `/api/resource/<camera\|mic\|speaker\|lcd\|uart>` | Exact paths, PID, systemd owner and consumers |

Envelopes advertise `contract_version: 2`, `catalog_version: 2`, `host: "pi"`,
`source: "pi"` and UNIX seconds `observed_at`. Unit rows identify `systemd` as their
source and retain observation age and `stale`. `can_move` describes potential effect,
not execution permission. `motion_owner` is `manual`, `follow_me`, `navigation`
or null. Unknown contract versions are read only.

`requested` is the current manager's intent. `state` distinguishes `starting`,
`ready`, `stopping`, `failed`, `partial` and `stopped`; `running` observes systemd
members. `ready` requires intent, installed active members, and current consent
for the matching owner for moving tasks. Move/turn also require `available: true`
and `stop_verified: true`; unknown/unverified capabilities are not readiness.
An active target alone is insufficient.
Restarting API does not restore movement tasks. S0 is the base consumer; S1 requires
separate operator preparation.

## Minimal profiles and options

`POST /api/logic/feature/<name>` accepts boolean `enabled` and object `options`.
Unknown keys/values are rejected. Repeating a start is idempotent; changing an
active task's options requires stop first. Existing aliases remain supported.

The catalog's `option_schema` supplies the field, default and permitted choices.
A moving start also requires the original operator envelope at the top level:
`generation`, `seq`, `source: "manual"`, `ts`, `ttl_ms` (1–500 ms) and `request_id`.
The server rejects stale or replayed intents without rewriting time or generation.
Accepted generation and request ID are atomically written before a producer starts
to `/run/rider-motion/feature_state.json`, under `service_intents[unit]`.
If writing fails, movement start fails closed. Producers bind that generation for
their lifetime. A later ARM of the same owner cannot authorize an old task;
stop the previous task, confirm STOP, then prepare and start a new plan.

| Task | Options / effect |
| --- | --- |
| S0 | API, BUS, executor and telemetry; no arming |
| S1 | Same base, separate manual permission; never arms drives |
| S2 | RAW camera and frame feed |
| S3 | RAW/feed/tracker/controller; face or hand, one owner |
| S4 | RAW/feed/vision/obstacles/odometry/map/navigator; navigation consent |
| S5 | `domain: voice\|asr\|tts`, default voice; no Google |
| S6 | RAW/feed/tracker; passive, no controller or tracking.pose actuation |
| S7 | `provider: local\|pc`; local vision/obstacles or offload only |
| S8 | Passive mapping without navigator |
| S9 | Map stack and navigator; navigation consent |
| S10 | `domain: text\|voice\|asr\|tts\|vision\|google`; default text with the chat-only HTTP worker |
| S11 | `tool: edge\|ssd\|raw`, default edge; exactly one tool, no GUI/Jupyter |

Optional targets are task markers. Starting one through systemctl does not execute
the scenario; the manager owns explicit catalog members. Camera/feed can be shared.
Offload consumes the existing feed/file, without a second camera fallback.
Jupyter remains a manually operated tool.

## Ownership and completion

Task, administration and recovery actions share one lock. The manager starts only
the required difference and stops only its own units no longer required by base or
another consumer. Processes already running at manager startup have an `external`
consumer and are never stopped implicitly; operators can inspect and stop them
explicitly. Catalog and detected process remain visible.

All profiles inherit the read-only baseline; starting the executor creates DISARMED
and never arms actuators. Start aborts on first error and rolls back its new units. Incomplete rollback is
`partial`; another stop can complete cleanup. RAW/EDGE/SSD or control-owner conflicts
are denied without stopping another task. Administration cannot stop/restart a
leased resource. Enable of optional/dev/manual services is forbidden; autostart
is a separate decision.

Autonomy completion revokes consent and waits for confirmed STOP through the shared
gate before releasing resources. Missing ACK/timeout retains resources with
`stop_unconfirmed`. Start/restart never arms actuators. See [safety](apps/safety.md).
Automatic tests use isolated fakes; physical actuator trials are manual only with
explicit operator consent for the specific plan.

## Diagnostics and recovery

Diagnostics never initialize the SDK. UART is a separate resource owned by one
executor; sensor-reader consumes BUS telemetry. Camera covers `/dev/video*` only;
SPI/framebuffer belongs to LCD. Missing devices are `unavailable`, read failures
are `unknown`, and `free` is null in both cases.

Stop the owning task first. `release` never kills processes by default. Manual
recovery requires `force: true`, `operator_consent: true` and exact currently
observed PIDs. Responses show owners, consumers and effects. SIGTERM affects only
those PIDs; no automatic SIGKILL/restart. UART, LCD and base are protected. Viewing
a device never grants recovery or movement consent.

The API LCD idle guard observes ownership and publishes an operator idle hint.
It never releases LCD resources automatically. Inventory errors leave power and
presentation unknown (`on: null`); a free SPI descriptor does not prove that the
screen is dark. Boot, rendering policy and the physical orientation are unchanged.

## Observation and installation migration

A shared snapshot uses one systemctl show for the catalog, a 0.75 s TTL and a
refresh lock. Mutations invalidate the cache. Failures retain observation age,
mark stale and remove readiness. This bounds reads; it is not a battery measurement.

`scripts/systemd-sync.sh` defaults to a **read-only plan**. The plan includes missing
S6/S7/S10 availability; repository source does not imply installation. After reading
installation state and reviewing the plan, an operator may run:

```bash
./scripts/systemd-sync.sh
sudo ./scripts/systemd-sync.sh --apply
# separate boot ownership decision; no process start/stop:
sudo ./scripts/systemd-sync.sh --apply --consolidate-boot
# backup path printed by apply:
sudo ./scripts/systemd-sync.sh --rollback /etc/systemd/system/_rider_catalog_<stamp>
```

Apply links only catalog units, records backup/manifest and daemon-reloads. It does
not remove unrelated units/drop-ins, change default target, networking, SSH or
LCD/boot parameters, and never starts/stops/restarts processes or uses --now/reboot.
`--with-dev` is accepted for compatibility but installs no legacy units. Separate
consolidate-boot enables minimal/splash/LCD/Wi-Fi and disables redundant enabled
units and optional tasks, without stopping processes. Rollback refuses to overwrite
units changed since migration. Unit migration is separate from ordinary application
preview in [deployment](DEPLOYMENT.md).


## Producer acceptance and selected runtime

Follow and navigation publish a per-unit heartbeat in the intent journal directory:
`rider-tracking-controller.service.json` or `rider-navigator.service.json`.
Readiness requires fresh `observed_at` (at most 3 s), `accepted: true`,
`active: true`, and the exact accepted `generation/request_id`. Waiting for a
tracking target may be an accepted task, without physical movement.
The start response can succeed with `state: starting`; process start is not
producer acceptance. Missing ACK remains unavailable and becomes `partial` after
the startup window. Starting the same owner in a new generation never accepts
the old request. Navigator consumes the journal once; no synthetic HTTP start
or refreshed caller timestamp is sent.

ASR and TTS share the existing `rider-voice-web.service` process and port 8092.
An ASR profile imports only Vosk; TTS imports only Piper. The requested domains
are the union of current task/admin consumers; stopping the last domain clears
its model cache, and stopping the last consumer releases the worker.
A domain heartbeat reports actual backend import/model availability and PID.
A task becomes ready only for the domains it requested. Full `voice` adds the
listener CLI and chat explicitly, with the worker started first. The shipped
`VOICE_WEB_LLM_PROVIDER=stub` makes full conversation unavailable; ASR/TTS remain
independent. No package installation or model download happens during startup.
The worker loads the declared local voice configuration, rejects cloud TTS
overrides, and does not source a login shell for unrelated credentials.

The text profile starts only the existing HTTP worker with its chat domain. It requires a configured executable local backend and its model; the shipped `stub` is explicitly unavailable. It does not import ASR/TTS or claim microphone/speaker resources. `/api/chat/send` resolves this selected worker from its fresh matching PID/heartbeat when no explicit `CHAT_REMOTE_URL` is configured. Echo is a legacy fallback and never evidence of AI readiness.

The selected-worker endpoint is a same-host HTTP route. The producer and consumer require a literal loopback address, an explicit valid port and the fixed `/api/chat` path; wildcard listener binds map to loopback. Invalid binds publish an unavailable chat capability with `chat_worker_endpoint_requires_loopback_bind` and do not advertise an endpoint. The internal client bypasses environment proxies and rejects redirects. An explicit `CHAT_REMOTE_URL` keeps its separate configured-backend transport.

ASR/TTS readiness requires actual successful construction and caching of only the selected model (`model_loaded: true`), rather than an import and path check. A corrupt model produces `*_model_load_failed`; no audio device is opened by this validation.

`runtime_modules` describes required imports per catalog unit. Preflight checks
only the selected profile and returns `runtime_dependencies_missing` before
starting units. Voice workers also check their selected backend/models using
their own systemd environment, so API-side package discovery does not claim model
or ABI compatibility. WSL tools and optional ML remain outside the baseline;
see [environment policy](ENVIRONMENT_POLICY.md).

The API's thread lock and a bounded filesystem lock (`feature_state.lock`)
serialize mutation and recovery across maintenance processes. Separate CLI
recovery reads recorded consumers as well as live observations. Missing or
unreadable lock/journal is a failed operation, never permission to release a
resource. Mutations invalidate systemd observations before and after execution.
Provider registry PATCH routes are not task start/stop; use catalog task options
for selecting a minimal running domain. Legacy provider state/health stays
diagnostic until its global mode side effects are removed.

## Legacy callers during panel migration

The old panel keeps observation and STOP. Its task starts, return-home and resource recovery buttons are disabled until the catalog v2 operator panel supplies consent and current inventory. Unknown/unavailable resources are shown explicitly. CLI moving starts require an interactive operator TTY, a prior explicit ARM with a concrete plan, and `--control-file`: a bounded JSON file containing the exact fresh envelope from the current operator action (generation, request_id, source, seq, ts, ttl_ms). The manager validates it unchanged; the CLI never arms, renews timestamps or creates consent. Prepare the file immediately before submission; expired intent is rejected. STOP requires no file.
