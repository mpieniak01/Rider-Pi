# Physical robot safety

A lightweight robot has inertia, balance and braking distance. Software consent
and SDK ACK are not physical completion proof.

## Test categories

- Full automated suites and E2E run in WSL/CI. Before collection, isolation
  blocks SDK, devices, production BUS, robot connections, service mutations and
  subprocess bypasses. Hardware mocks are explicit; hardware/physical_motion
  markers never invoke real-device tests automatically.
- On Pi, check selected nonmoving camera/LCD/telemetry functions. Diagnostics
  never arm, clear E-Stop or start autonomy.
- Drive, yaw, height, balance, actions and moving autonomy require operator
  consent for a concrete manual attempt. pytest/E2E/CI, deployment, schedules
  and panel loading never invoke such attempts.

Camera/service/WSL installation/deployment permission is not movement consent.
See [environment policy](../ENVIRONMENT_POLICY.md).

## Operator and cable

Treat a development robot on a power cable as unprepared until confirmed.
For EACH attempt, describe actuator, direction, normalized speed and duration.
The operator confirms space, surface, cable and prepared STOP. Check versions,
UART owner and fresh gate state. One short manual attempt, STOP, physical
inspection and a recorded result. Each next attempt needs new consent.
Never raise limits to simplify diagnostics.

## Guards

One DISARMED/ARMED/ESTOP gate covers every actuator. Owner and lease bound
consent; generation/seq/ts/TTL reject old or foreign commands. Task intents stop
old follow/nav producers capturing a new ARM. Lock plus exact UART ownership
exclude second SDK owners. SDK guard blocks constructor reset. MOTION_ENABLE=0
is an additional veto. Flag/GPIO latch E-Stop; persistence failure cannot
interrupt in-memory STOP and appears as persistence_error. UART/STOP faults
lower readiness and block subsequent ARM.

DRY_RUN/BRIDGE_READONLY/profile names/HTTP success do not prove global inhibition.
confirmed STOP requires terminal ACK; physical_completion remains unverified.
Height/balance/actions remain blocked pending manual interruption characterization.

## Commands

make safety-status and diag_motion-status.py only read. make safemode and
sys_emergency-stop.py on require E-Stop ACK. make stop-all first requires
confirmed STOP before stopping application units. manual_motion-probe.py
requires an interactive terminal, plan and typed one-use token: one attempt,
STOP in finally. It refuses CI/pytest and uncharacterized capabilities.
Legacy burst/cascade/move smokes/demos are disabled. Separate consent clears
E-Stop to DISARMED without replay; diagnostics/deployment never remove flags.

## Limits

SIGTERM runs cleanup. Physical STOP after SIGKILL, UART loss or Pi power loss is
unverified. Firmware may retain its last target; a Pi process lease is not an
independent hardware safeguard. Manual characterization is required.
See [motion](motion.md). Preserve LCD rotation 270, boot, Wi-Fi and SSH.


## Command validation and execution evidence

The API and executor gate validate commands in ordered stages: panel identity,
generation/sequence and freshness, execution context, consent and actuator
parameters. Invalid JSON types and numbers overflowing conversion produce a
validation rejection without consuming a sequence or changing consent. BUS
command timestamps are JSON numbers, not strings. STOP and E-Stop retain
priority; an explicit `expected_generation` still binds a particular STOP.
Idempotent ARM within the same session does not extend its consent lease.

Snapshots require an integer `contract_version` and a finite numeric
`observed_at`; booleans cannot stand in for numbers. Invalid freshness limits
return UNKNOWN. A stale snapshot may retain historical operator permission,
while `can_move` and fresh authorization confirmation remain disabled.

A matching ACK must identify the same request/action/source, generation and
typed sequence. Its observation time must be finite and no earlier than the
send time. Contradictory status/accepted pairs do not confirm execution; a bad
history entry cannot hide later valid evidence. Missing trustworthy evidence
remains pending. HTTP projection preserves source precedence: partial results,
ACK, persisted configuration/completed computation, task, observed resource,
then application result. HTTP 200 or task acceptance alone never invents
physical completion.

CORS protection snapshots header names before removing legacy grants so that
mutating the collection cannot skip adjacent entries. Host/Origin checks,
explicit upload handling and consent limits remain active.
